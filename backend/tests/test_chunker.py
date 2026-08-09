"""AudioChunker(音声チャンク化)の単体テスト。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audio.chunker import AudioChunker, resample_audio  # noqa: E402


def _sine_wave(seconds: float, sample_rate: int, freq: float = 440.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * sample_rate), endpoint=False)
    return (0.1 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_resample_audio_changes_length():
    mono = _sine_wave(1.0, 48000)
    resampled = resample_audio(mono, 48000, 16000)
    assert abs(len(resampled) - 16000) <= 2


def test_resample_audio_noop_when_same_rate():
    mono = _sine_wave(0.5, 16000)
    resampled = resample_audio(mono, 16000, 16000)
    assert len(resampled) == len(mono)


def test_chunker_emits_chunks_at_expected_interval():
    sample_rate = 48000
    chunker = AudioChunker(source_sample_rate=sample_rate, chunk_seconds=2.0, target_sample_rate=16000)

    # 5秒分のステレオ音声を1024フレーム単位で供給する(WASAPIコールバックを模倣)
    total_seconds = 5.0
    frame_block = 1024
    total_frames = int(total_seconds * sample_rate)

    mono = _sine_wave(total_seconds, sample_rate)
    stereo = np.stack([mono, mono], axis=1)

    all_chunks = []
    for start in range(0, total_frames, frame_block):
        block = stereo[start : start + frame_block]
        if len(block) == 0:
            continue
        all_chunks.extend(chunker.feed(block))

    # 5秒/2秒チャンク => 少なくとも2つのチャンクが生成される
    assert len(all_chunks) >= 2
    for chunk in all_chunks:
        assert chunk.sample_rate == 16000
        assert chunk.end_ms > chunk.start_ms

    final = chunker.flush()
    if final is not None:
        assert final.sample_rate == 16000


def test_chunker_flush_returns_none_when_buffer_empty():
    chunker = AudioChunker(source_sample_rate=16000, chunk_seconds=2.0, target_sample_rate=16000)
    assert chunker.flush() is None
