"""WebSocketによるリアルタイム配信(要件定義書 第16章)の疎通テスト。"""
from __future__ import annotations

import asyncio


def test_websocket_receives_broadcast_message(client):
    import app.api.ws as ws_module

    meeting_id = 999

    with client.websocket_connect(f"/ws/meetings/{meeting_id}") as websocket:
        asyncio.run(
            ws_module.manager.broadcast(
                meeting_id,
                {"type": "utterance", "utterance": {"id": 1, "text": "テスト発言"}},
            )
        )
        data = websocket.receive_json()
        assert data["type"] == "utterance"
        assert data["utterance"]["text"] == "テスト発言"
