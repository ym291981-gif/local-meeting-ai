"""まとめJSON検証・マージ保護・レガシー変換の単体テスト。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.minutes import (  # noqa: E402
    MinutesData,
    _validate_minutes_json,
    is_catastrophic_shrink,
    legacy_to_sections,
    merge_minutes,
    normalize_summary_mode,
    system_prompt_for_mode,
)


def _sections_dict(*sections: dict) -> dict:
    return {"sections": list(sections)}


def test_validate_accepts_well_formed_sections_json():
    raw = json.dumps(
        _sections_dict(
            {"title": "学びのポイント", "items": [{"text": "差分更新の重要性"}]},
            {"title": "用語", "items": [{"text": "embedding"}]},
        ),
        ensure_ascii=False,
    )
    result = _validate_minutes_json(raw)
    assert result is not None
    assert result["sections"][0]["title"] == "学びのポイント"
    assert result["sections"][0]["items"][0]["text"] == "差分更新の重要性"


def test_validate_rejects_invalid_json_syntax():
    assert _validate_minutes_json("これはJSONではありません") is None


def test_validate_rejects_missing_sections():
    assert _validate_minutes_json(json.dumps({"topics": []})) is None


def test_validate_rejects_item_without_text():
    raw = json.dumps(
        {"sections": [{"title": "要点", "items": [{"note": "textなし"}]}]},
        ensure_ascii=False,
    )
    assert _validate_minutes_json(raw) is None


def test_minutes_data_roundtrip():
    data = _sections_dict({"title": "概要", "items": [{"text": "導入"}]})
    minutes = MinutesData.from_dict(data)
    assert minutes.to_dict() == data


def test_merge_keeps_existing_sections_when_llm_drops_them():
    current = MinutesData(
        sections=[
            {"title": "議題A", "items": [{"text": "背景確認"}]},
            {"title": "決定事項", "items": [{"text": "来週再議"}]},
        ]
    )
    incoming = MinutesData(
        sections=[
            {"title": "学びのポイント", "items": [{"text": "新トピック"}]},
        ]
    )
    merged = merge_minutes(current, incoming)
    titles = [s["title"] for s in merged.sections]
    assert titles == ["議題A", "決定事項", "学びのポイント"]
    assert merged.sections[0]["items"][0]["text"] == "背景確認"


def test_merge_updates_matching_item_in_place():
    current = MinutesData(
        sections=[
            {
                "title": "ToDo",
                "items": [{"text": "資料作成", "owner": None}],
            }
        ]
    )
    incoming = MinutesData(
        sections=[
            {
                "title": "ToDo",
                "items": [{"text": "資料作成", "owner": "田中", "deadline": "2026-09-01"}],
            }
        ]
    )
    merged = merge_minutes(current, incoming)
    assert len(merged.sections) == 1
    assert len(merged.sections[0]["items"]) == 1
    assert merged.sections[0]["items"][0]["owner"] == "田中"
    assert merged.sections[0]["items"][0]["deadline"] == "2026-09-01"


def test_catastrophic_shrink_detects_item_drop():
    current = MinutesData(
        sections=[
            {
                "title": "要点",
                "items": [{"text": "A"}, {"text": "B"}, {"text": "C"}, {"text": "D"}],
            }
        ]
    )
    incoming = MinutesData(
        sections=[{"title": "要点", "items": [{"text": "D"}]}]
    )
    assert is_catastrophic_shrink(current, incoming) is True


def test_catastrophic_shrink_allows_additive_update():
    current = MinutesData(
        sections=[{"title": "要点", "items": [{"text": "A"}, {"text": "B"}, {"text": "C"}, {"text": "D"}]}]
    )
    incoming = MinutesData(
        sections=[
            {
                "title": "要点",
                "items": [
                    {"text": "A"},
                    {"text": "B"},
                    {"text": "C"},
                    {"text": "D"},
                    {"text": "E"},
                ],
            }
        ]
    )
    assert is_catastrophic_shrink(current, incoming) is False


def test_legacy_to_sections_maps_fixed_keys():
    sections = legacy_to_sections(
        topics=[{"title": "A案件"}],
        decisions=[{"text": "納期変更"}],
        todos=[{"task": "資料修正", "owner": "鈴木", "deadline": "2026-08-25"}],
        pending_items=[],
        confirmations=[{"text": "予算確認"}],
        changes_from_previous=[],
    )
    by_title = {s["title"]: s["items"] for s in sections}
    assert by_title["議題"][0]["text"] == "A案件"
    assert by_title["決定事項"][0]["text"] == "納期変更"
    assert by_title["ToDo"][0]["text"] == "資料修正"
    assert by_title["ToDo"][0]["owner"] == "鈴木"
    assert by_title["確認事項"][0]["text"] == "予算確認"


def test_normalize_summary_mode_and_prompt():
    assert normalize_summary_mode("STUDY") == "study"
    assert normalize_summary_mode("unknown") == "auto"
    assert "勉強会" in system_prompt_for_mode("study")
    assert "sections" in system_prompt_for_mode("auto")
