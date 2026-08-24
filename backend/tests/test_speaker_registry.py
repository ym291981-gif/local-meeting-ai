"""オンライン話者クラスタリング(SpeakerRegistry)の単体テスト。

実際のpyannoteモデルは使わず、既知のembeddingベクトルを直接与えて
「似ているembeddingは同一話者にまとめられ、似ていないembeddingは新規話者になる」
という中核ロジックを検証する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import Meeting  # noqa: E402
from app.pipeline.diarization import (  # noqa: E402
    DiarizedTurn,
    SpeakerRegistry,
    assign_local_labels,
    cosine_distance,
    l2_normalize,
)


def _make_meeting(session_local) -> int:
    db = session_local()
    meeting = Meeting(title="テスト会議")
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    meeting_id = meeting.id
    db.close()
    return meeting_id


def test_similar_embeddings_are_assigned_to_same_speaker(test_db):
    meeting_id = _make_meeting(test_db)
    db = test_db()
    registry = SpeakerRegistry(db, meeting_id, similarity_threshold=0.3)

    embedding_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    embedding_a_similar = np.array([0.98, 0.02, 0.0], dtype=np.float32)

    speaker1 = registry.assign(embedding_a)
    speaker2 = registry.assign(embedding_a_similar)

    assert speaker1.id == speaker2.id
    assert speaker1.label == "speaker_01"


def test_dissimilar_embeddings_create_new_speakers(test_db):
    meeting_id = _make_meeting(test_db)
    db = test_db()
    registry = SpeakerRegistry(db, meeting_id, similarity_threshold=0.3)

    embedding_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    embedding_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)  # 直交 -> コサイン距離1.0

    speaker1 = registry.assign(embedding_a)
    speaker2 = registry.assign(embedding_b)

    assert speaker1.id != speaker2.id
    assert speaker1.label == "speaker_01"
    assert speaker2.label == "speaker_02"


def test_centroid_updates_as_running_mean(test_db):
    meeting_id = _make_meeting(test_db)
    db = test_db()
    registry = SpeakerRegistry(db, meeting_id, similarity_threshold=0.3)

    embedding_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    embedding_a2 = np.array([0.9, 0.1, 0.0], dtype=np.float32)

    speaker1 = registry.assign(embedding_a)
    assert speaker1.embedding_count == 1

    speaker1_updated = registry.assign(embedding_a2)
    assert speaker1_updated.id == speaker1.id
    assert speaker1_updated.embedding_count == 2
    centroid = np.asarray(speaker1_updated.embedding_centroid, dtype=np.float32)
    assert abs(float(np.linalg.norm(centroid)) - 1.0) < 1e-5


def test_assign_local_labels_clusters_once_per_label(test_db):
    meeting_id = _make_meeting(test_db)
    db = test_db()
    registry = SpeakerRegistry(db, meeting_id, similarity_threshold=0.3)
    embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    turns = [
        DiarizedTurn(start_ms=0, end_ms=1000, local_label="SPEAKER_00", embedding=embedding),
        DiarizedTurn(start_ms=2000, end_ms=3000, local_label="SPEAKER_00", embedding=embedding),
        DiarizedTurn(
            start_ms=4000,
            end_ms=5000,
            local_label="SPEAKER_01",
            embedding=np.array([0.0, 1.0, 0.0], dtype=np.float32),
        ),
    ]

    mapping = assign_local_labels(registry, turns)

    assert mapping["SPEAKER_00"].id != mapping["SPEAKER_01"].id
    assert mapping["SPEAKER_00"].embedding_count == 1
    assert mapping["SPEAKER_01"].embedding_count == 1


def test_default_threshold_merges_moderate_cosine_distance(test_db):
    """コサイン距離0.5は旧閾値0.45では分裂し、新既定0.65では同一話者になる。"""
    meeting_id = _make_meeting(test_db)
    db = test_db()
    registry = SpeakerRegistry(db, meeting_id, similarity_threshold=0.65)

    embedding_a = np.array([1.0, 0.0], dtype=np.float32)
    embedding_b = np.array([0.5, np.sqrt(0.75)], dtype=np.float32)  # コサイン類似度0.5
    assert abs(cosine_distance(embedding_a, embedding_b) - 0.5) < 1e-5

    speaker1 = registry.assign(embedding_a)
    speaker2 = registry.assign(embedding_b)
    assert speaker1.id == speaker2.id


def test_l2_normalize_unit_length():
    vec = l2_normalize(np.array([3.0, 4.0], dtype=np.float32))
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-6

