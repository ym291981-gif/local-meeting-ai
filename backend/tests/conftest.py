"""pytest共通フィクスチャ。

実際のGPU/音声デバイス/Ollamaサーバーに依存しないよう、DBはテスト用の一時
SQLiteに切り替え、パイプラインオーケストレーターはFakeOrchestratorへ置き換える。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_orchestrator  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.models import Base  # noqa: E402


class FakeOrchestrator:
    """実際の音声取得・AI処理を行わず、呼び出し履歴のみ記録するテスト用ダブル。"""

    def __init__(self) -> None:
        self.started: list[int] = []
        self.stopped: list[int] = []
        self.min_speakers_args: list[int | None] = []
        self.summary_mode_args: list[str] = []

    def start_meeting(
        self,
        meeting_id: int,
        min_speakers: int | None = None,
        summary_mode: str = "auto",
    ) -> None:
        self.started.append(meeting_id)
        self.min_speakers_args.append(min_speakers)
        self.summary_mode_args.append(summary_mode)

    def stop_meeting(self, meeting_id: int, timeout: float = 60.0) -> None:
        self.stopped.append(meeting_id)

    def is_running(self, meeting_id: int) -> bool:
        return meeting_id in self.started and meeting_id not in self.stopped

    def bind_loop(self, loop) -> None:  # noqa: ANN001
        pass


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    return testing_session_local


@pytest.fixture()
def client(test_db):
    import app.main as main_module

    fake_orchestrator = FakeOrchestrator()
    main_module.app.dependency_overrides[get_orchestrator] = lambda: fake_orchestrator

    with TestClient(main_module.app) as c:
        c.fake_orchestrator = fake_orchestrator
        yield c

    main_module.app.dependency_overrides.clear()
