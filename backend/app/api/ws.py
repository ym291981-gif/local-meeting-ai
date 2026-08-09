"""会議のリアルタイム更新(文字起こし・議事録)をブラウザへ配信するWebSocket。"""
from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """会議IDごとに接続中のWebSocketクライアントを管理し、更新をブロードキャストする。"""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, meeting_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[meeting_id].add(websocket)

    def disconnect(self, meeting_id: int, websocket: WebSocket) -> None:
        self._connections[meeting_id].discard(websocket)

    async def broadcast(self, meeting_id: int, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(meeting_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(meeting_id, ws)


manager = ConnectionManager()


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_ws(websocket: WebSocket, meeting_id: int) -> None:
    await manager.connect(meeting_id, websocket)
    try:
        while True:
            # クライアントからの送信は現状使わないが、受信ループでdisconnectを検知する
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(meeting_id, websocket)
    except Exception:
        logger.exception("WebSocket処理中にエラーが発生しました")
        manager.disconnect(meeting_id, websocket)
