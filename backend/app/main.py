"""FastAPIエントリポイント。

要件定義書の方針(第36.3・36.4章)に従い、テスト専用のファイルアップロード機能等は
一切実装しない。UIはこのアプリが配信する静的ファイル(frontend/static)のみ。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import meetings, minutes, participants, speakers, transcript, ws
from app.config import get_settings
from app.db.session import init_db
from app.state import build_app_state

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_STATIC_DIR = BACKEND_DIR.parent / "frontend" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    app_state = build_app_state(broadcast=ws.manager.broadcast)
    app_state.orchestrator.bind_loop(asyncio.get_running_loop())

    app.state.settings = app_state.settings
    app.state.orchestrator = app_state.orchestrator

    logger.info("アプリケーションを起動しました")
    yield
    logger.info("アプリケーションを終了します")


app = FastAPI(title="リアルタイムAI議事録・文書活用支援ツール", lifespan=lifespan)

app.include_router(meetings.router)
app.include_router(participants.router)
app.include_router(speakers.router)
app.include_router(transcript.router)
app.include_router(minutes.router)
app.include_router(ws.router)

if FRONTEND_STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_STATIC_DIR), html=True), name="static")
else:  # pragma: no cover - フロントエンド未配置環境向けの保険
    logger.warning("フロントエンド静的ファイルが見つかりません: %s", FRONTEND_STATIC_DIR)
