"""話者クラスタリングの診断スクリプト(製品機能ではない)。

WAVを8秒チャンクに分け、pyannoteのローカル話者数と、オンライン割当後の
グローバル話者数・最近傍コサイン距離を表示する。閾値調整の材料にする。

実行方法:
    cd backend
    python ..\\scripts\\inspect_speaker_clustering.py --wav tests\\fixtures\\demo_meeting.wav
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.audio.chunker import resample_audio  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.models import Base, Meeting, Speaker  # noqa: E402
from app.pipeline.diarization import (  # noqa: E402
    DiarizationEngine,
    SpeakerRegistry,
    assign_turns,
    cosine_distance,
    resolve_min_speakers,
)


def load_wav_mono16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    pcm16 = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        pcm16 = pcm16.reshape(-1, n_channels).mean(axis=1)
    return resample_audio(pcm16, sample_rate, 16000)


def main() -> None:
    parser = argparse.ArgumentParser(description="話者クラスタリング診断")
    parser.add_argument("--wav", required=True, help="診断するWAVファイル")
    parser.add_argument("--chunk-seconds", type=float, default=8.0)
    parser.add_argument("--min-speakers", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    min_speakers = resolve_min_speakers(
        args.min_speakers, settings.diarization_min_speakers
    )
    samples = load_wav_mono16k(Path(args.wav))
    sample_rate = 16000
    chunk_len = int(args.chunk_seconds * sample_rate)

    engine = DiarizationEngine(
        device=settings.diarization_device,
        hf_token=settings.hf_token,
        embedding_batch_size=settings.diarization_embedding_batch_size,
    )

    sqlite = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=sqlite)
    session_local = sessionmaker(bind=sqlite, autoflush=False, autocommit=False)
    db = session_local()
    meeting = Meeting(title="clustering-inspect")
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    registry = SpeakerRegistry(
        db, meeting.id, similarity_threshold=settings.speaker_similarity_threshold
    )

    print(f"threshold={settings.speaker_similarity_threshold}")
    print(
        f"device={settings.diarization_device}  "
        f"duration={len(samples) / sample_rate:.1f}s  "
        f"min_speakers={min_speakers}"
    )
    print()

    for index, start in enumerate(range(0, len(samples), chunk_len)):
        chunk = samples[start : start + chunk_len]
        if len(chunk) < sample_rate // 2:
            continue
        turns = engine.diarize_chunk(chunk, sample_rate, min_speakers=min_speakers)
        local_labels = sorted({turn.local_label for turn in turns})
        assigned = assign_turns(registry, turns)
        global_labels = sorted({speaker.label for speaker in assigned})
        print(
            f"chunk {index:02d}  {len(chunk) / sample_rate:4.1f}s  "
            f"local={local_labels or ['(none)']}  "
            f"global={global_labels or ['(none)']}"
        )
        speakers = registry._active_speakers()
        if len(speakers) >= 2:
            centroids = [
                np.asarray(speaker.embedding_centroid, dtype=np.float32) for speaker in speakers
            ]
            distances = [
                cosine_distance(centroids[i], centroids[j])
                for i in range(len(centroids))
                for j in range(i + 1, len(centroids))
            ]
            print(
                f"         pairwise min/max distance: {min(distances):.3f} / {max(distances):.3f}"
            )

    speakers = (
        db.query(Speaker)
        .filter(Speaker.meeting_id == meeting.id, Speaker.merged_into_id.is_(None))
        .all()
    )
    print()
    print(f"最終的なアクティブ話者数: {len(speakers)}")
    for speaker in speakers:
        print(f"  {speaker.label}  embedding_count={speaker.embedding_count}")
    db.close()


if __name__ == "__main__":
    main()
