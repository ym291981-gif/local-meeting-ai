"""設定の読み込みと、WindowsでのcuDNN競合回避。"""
from __future__ import annotations

import sys

from app.config import Settings


def test_windows_both_cuda_forces_diarization_cpu() -> None:
    settings = Settings(whisper_device="cuda", diarization_device="cuda")
    if sys.platform == "win32":
        assert settings.diarization_device == "cpu"
    else:
        assert settings.diarization_device == "cuda"


def test_whisper_cpu_can_keep_diarization_cuda() -> None:
    settings = Settings(whisper_device="cpu", diarization_device="cuda")
    assert settings.diarization_device == "cuda"
