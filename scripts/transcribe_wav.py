"""Step2動作確認: WAVファイルをfaster-whisperで文字起こしする単体検証スクリプト。

record_sample.py で録音したWAVや、generate_demo_audio.py で生成したデモ音声を
直接指定して、Whisperの認識品質のみを素早く確認できる
(このスクリプト自体は「ファイル読み込み機能」ではなく、開発検証用途に限定する。
要件定義書 第36.3章)。

実行方法:
    cd backend
    python ..\scripts\transcribe_wav.py --wav ..\backend\tests\fixtures\demo_meeting.wav
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.audio.chunker import resample_audio  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.pipeline.asr import WhisperTranscriber  # noqa: E402


def load_wav_mono16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    pcm16 = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        pcm16 = pcm16.reshape(-1, n_channels).mean(axis=1)
    return resample_audio(pcm16, sample_rate, 16000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", type=str, required=True)
    args = parser.parse_args()

    settings = get_settings()
    samples = load_wav_mono16k(Path(args.wav))

    transcriber = WhisperTranscriber(
        model_name=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )

    print("文字起こし中...")
    segments = transcriber.transcribe_chunk(samples, 16000, chunk_start_ms=0)
    for seg in segments:
        print(f"[{seg.start_ms/1000:6.1f}s - {seg.end_ms/1000:6.1f}s] {seg.text}")


if __name__ == "__main__":
    main()
