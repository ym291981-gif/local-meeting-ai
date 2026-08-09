"""Step1動作確認: PC内部音声(WASAPIループバック)を指定秒数録音し、WAVへ保存する。

何か音声を再生している状態(音楽・デモ音声・Zoom会議音声等)で実行することで、
「マイクを使わずにPC内部音声を取得できているか」を確認できる。

実行方法:
    cd backend
    python ..\scripts\record_sample.py --seconds 10 --out ..\backend\tests\fixtures\sample.wav
"""
from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.audio.capture import WasapiLoopbackCapture  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--out", type=str, default="sample.wav")
    args = parser.parse_args()

    frames: list[np.ndarray] = []
    print(f"{args.seconds}秒間、内部音声を録音します。音声を再生してください...")

    with WasapiLoopbackCapture() as capture:
        start = time.time()
        for chunk in capture.iter_frames():
            frames.append(chunk)
            if time.time() - start >= args.seconds:
                break
        sample_rate = capture.sample_rate
        channels = capture.channels

    audio = np.concatenate(frames, axis=0)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pcm16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())

    print(f"保存しました: {out_path} ({sample_rate}Hz, {channels}ch)")


if __name__ == "__main__":
    main()
