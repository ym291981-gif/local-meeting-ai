"""アプリ全体の設定。.env から読み込み、コード側で使いやすい形に変換する。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    # Whisper
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"
    whisper_model: str = "large-v3-turbo"

    # pyannote
    diarization_device: str = "cuda"
    hf_token: str = ""
    diarization_embedding_batch_size: int = 4

    # Ollama
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b-instruct-2507-q4_K_M"

    # Audio
    audio_chunk_seconds: float = 8.0
    audio_target_sample_rate: int = 16000

    # Minutes
    minutes_update_char_threshold: int = 800
    minutes_update_interval_seconds: float = 180.0

    # Speaker clustering
    # コサイン距離がこの値以下なら同一話者。0.45だと短い発話で分裂しやすい。
    speaker_similarity_threshold: float = 0.65

    # DB
    database_url: str = f"sqlite:///{(DATA_DIR / 'meeting_ai.db').as_posix()}"

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
