"""FastAPI依存性注入用のヘルパー。"""
from __future__ import annotations

from fastapi import Request

from app.pipeline.orchestrator import PipelineOrchestrator


def get_orchestrator(request: Request) -> PipelineOrchestrator:
    return request.app.state.orchestrator
