"""議事録JSON検証ロジック(_validate_minutes_json)の単体テスト。

Qwen3の出力ゆらぎに対する防御ロジックが正しく機能するかを確認する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.minutes import MinutesData, _validate_minutes_json  # noqa: E402


def _full_minutes_dict() -> dict:
    return {
        "topics": [{"title": "A案件の納期"}],
        "decisions": [{"text": "納期を8月27日に変更する"}],
        "todos": [{"task": "資料を修正する", "owner": "鈴木", "deadline": "2026-08-25"}],
        "pending_items": [],
        "confirmations": [],
        "changes_from_previous": [],
    }


def test_validate_accepts_well_formed_json():
    raw = json.dumps(_full_minutes_dict(), ensure_ascii=False)
    result = _validate_minutes_json(raw)
    assert result is not None
    assert result["topics"][0]["title"] == "A案件の納期"


def test_validate_rejects_invalid_json_syntax():
    assert _validate_minutes_json("これはJSONではありません") is None


def test_validate_rejects_missing_required_keys():
    incomplete = {"topics": [], "decisions": []}
    assert _validate_minutes_json(json.dumps(incomplete)) is None


def test_validate_allows_extra_keys():
    data = _full_minutes_dict()
    data["extra_field"] = "無視されるべき"
    assert _validate_minutes_json(json.dumps(data)) is not None


def test_minutes_data_roundtrip():
    data = _full_minutes_dict()
    minutes = MinutesData.from_dict(data)
    assert minutes.to_dict() == data
