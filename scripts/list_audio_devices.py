"""Step1動作確認: WASAPIループバックデバイス(PC内部音声取得元)の一覧を表示する。

実行方法:
    cd backend
    python ..\scripts\list_audio_devices.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.audio.capture import get_default_loopback_device, list_loopback_devices  # noqa: E402


def main() -> None:
    print("=== 利用可能なWASAPIループバックデバイス ===")
    for device in list_loopback_devices():
        print(f"  [{device.index}] {device.name} ({device.sample_rate}Hz, {device.channels}ch)")

    print()
    default = get_default_loopback_device()
    print(f"既定のループバックデバイス: [{default.index}] {default.name}")
    print("(このデバイスから、Zoomの音声やデモ音声再生時の音声が取得されます)")


if __name__ == "__main__":
    main()
