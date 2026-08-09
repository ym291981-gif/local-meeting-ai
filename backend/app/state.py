"""アプリ全体で共有するシングルトン(AIモデル・オーケストレーター)の初期化。"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.pipeline.asr import WhisperTranscriber
from app.pipeline.diarization import DiarizationEngine
from app.pipeline.minutes import MinutesGenerator
from app.pipeline.orchestrator import BroadcastFn, PipelineOrchestrator


@dataclass
class AppState:
    settings: Settings
    orchestrator: PipelineOrchestrator


def build_app_state(broadcast: BroadcastFn) -> AppState:
    settings = get_settings()

    transcriber = WhisperTranscriber(
        model_name=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    diarizer = DiarizationEngine(
        device=settings.diarization_device,
        hf_token=settings.hf_token,
        embedding_batch_size=settings.diarization_embedding_batch_size,
    )
    minutes_generator = MinutesGenerator(host=settings.ollama_host, model=settings.ollama_model)

    orchestrator = PipelineOrchestrator(
        settings=settings,
        transcriber=transcriber,
        diarizer=diarizer,
        minutes_generator=minutes_generator,
        broadcast=broadcast,
    )
    return AppState(settings=settings, orchestrator=orchestrator)
