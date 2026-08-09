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
from app.pipeline.diarization import SpeakerRegistry  # noqa: E402


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
