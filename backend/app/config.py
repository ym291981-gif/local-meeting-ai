"""アプリ全体の設定。.env から読み込み、コード側で使いやすい形に変換する。"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    # Whisper
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"
    whisper_model: str = "large-v3-turbo"

    # pyannote。WindowsではWhisper(cuda)とのcuDNN競合を避けるため既定はcpu。
    diarization_device: str = "cpu"
    hf_token: str = ""
    diarization_embedding_batch_size: int = 4
    # 会議全体の話者上限ヒント。1以下は未指定(自動推定)。チャンクごとの下限ではない。
    diarization_min_speakers: int = 1

    # Ollama
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b-instruct-2507-q4_K_M"

    # Audio
    audio_chunk_seconds: float = 8.0
    audio_target_sample_rate: int = 16000

    # Minutes
    minutes_update_char_threshold: int = 300
    minutes_update_interval_seconds: float = 60.0

    # Diarization queue backpressure (chunks held with audio samples).
    # ~8 chunks ≈ 64s of audio at default AUDIO_CHUNK_SECONDS=8.
    diarize_queue_maxsize: int = 8

    # Speaker clustering
    # コサイン距離がこの値以下なら同一話者。0.45だと短い発話で分裂しやすい。
    speaker_similarity_threshold: float = 0.65

    # DB
    database_url: str = f"sqlite:///{(DATA_DIR / 'meeting_ai.db').as_posix()}"

    # Logging
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _avoid_windows_cudnn_conflict(self) -> Settings:
        if (
            sys.platform == "win32"
            and self.whisper_device.lower() == "cuda"
            and self.diarization_device.lower() == "cuda"
        ):
            logger.warning(
                "Windowsでは Whisper と pyannote を両方 cuda にすると cuDNN 競合で"
                "プロセスがクラッシュするため、話者分離は cpu に切り替えます"
            )
            self.diarization_device = "cpu"
        return self


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
