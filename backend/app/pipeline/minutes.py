"""Ollama経由でQwen3を呼び出し、まとめ(議事録/勉強会メモ等)を構造化データとして生成・更新する。

長時間会議の全文を毎回渡すのではなく、「現在のまとめ」+「直近の新規発言」だけを
渡して更新後のまとめを得る差分更新方式を採用する。

スキーマは固定カテゴリではなく、見出し＋箇条書きの sections 配列。
用途モード(meeting/study/summary/auto)はプロンプトのヒントのみで、見出しを強制しない。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import ollama

from app.db.models import (
    DEFAULT_SUMMARY_MODE,
    SUMMARY_MODE_AUTO,
    SUMMARY_MODE_MEETING,
    SUMMARY_MODE_STUDY,
    SUMMARY_MODE_SUMMARY,
)

logger = logging.getLogger(__name__)

_BASE_SYSTEM_PROMPT = """あなたは日本語の会議・勉強会・動画などの内容を整理するアシスタントです。
与えられた「これまでのまとめ(JSON)」と「新しい発言記録」から、まとめを更新してください。

出力は必ず次の形のJSONオブジェクトのみとしてください(説明文や前置きは不要):
{
  "sections": [
    { "title": "見出し", "items": [ { "text": "箇条書きの内容" } ] }
  ]
}

ルール:
- sections の各要素は title(文字列) と items(辞書の配列) を持つこと。
- items の各要素は少なくとも text(文字列) を持つこと。必要なら owner / deadline など追加フィールドを付けてよい。
- 既存のセクションと項目は、新しい発言と矛盾しない限り省略・削除しないこと。
- 内容に合わない見出しは無理に作らないこと。必要な見出しだけを使うこと。
- 新しい発言に含まれる情報のみ追加・更新し、憶測で情報を作らないでください。
- 発言中の細かな言い回しではなく、内容を整理して記載してください。
"""

_MODE_HINTS: dict[str, str] = {
    SUMMARY_MODE_MEETING: (
        "用途ヒント(議事録): 定例会議向け。"
        "議題・決定事項・ToDo・保留・確認などが自然なら使ってよいが、不要なら作らない。"
    ),
    SUMMARY_MODE_STUDY: (
        "用途ヒント(勉強会): 講義・勉強会向け。"
        "学びのポイント・用語・質疑・参考などが自然なら使ってよいが、不要なら作らない。"
    ),
    SUMMARY_MODE_SUMMARY: (
        "用途ヒント(要約): 動画・発表の要約向け。"
        "概要・章立て・要点・結論などが自然なら使ってよいが、不要なら作らない。"
    ),
    SUMMARY_MODE_AUTO: (
        "用途ヒント(自動): 内容から最適な見出しを自由に選んでまとめてください。"
    ),
}

_LEGACY_SECTION_MAP: list[tuple[str, str, str]] = [
    # (attribute-or-key, section title, item text field)
    ("topics", "議題", "title"),
    ("decisions", "決定事項", "text"),
    ("pending_items", "保留事項", "text"),
    ("confirmations", "確認事項", "text"),
    ("changes_from_previous", "前回からの変更事項", "text"),
]


@dataclass
class MinutesData:
    sections: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"sections": self.sections}

    @classmethod
    def empty(cls) -> "MinutesData":
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "MinutesData":
        sections = data.get("sections") if isinstance(data, dict) else None
        if not isinstance(sections, list):
            sections = []
        return cls(sections=sections)

    def item_count(self) -> int:
        total = 0
        for section in self.sections:
            items = section.get("items") if isinstance(section, dict) else None
            if isinstance(items, list):
                total += len(items)
        return total


def normalize_summary_mode(mode: str | None) -> str:
    if not mode:
        return DEFAULT_SUMMARY_MODE
    value = str(mode).strip().lower()
    if value in _MODE_HINTS:
        return value
    return DEFAULT_SUMMARY_MODE


def system_prompt_for_mode(summary_mode: str | None) -> str:
    mode = normalize_summary_mode(summary_mode)
    return f"{_BASE_SYSTEM_PROMPT}\n{_MODE_HINTS[mode]}\n"


def _normalize_key(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def legacy_to_sections(
    *,
    topics: list | None = None,
    decisions: list | None = None,
    todos: list | None = None,
    pending_items: list | None = None,
    confirmations: list | None = None,
    changes_from_previous: list | None = None,
) -> list[dict]:
    """旧固定6キーを sections 形式へ変換する。"""
    source = {
        "topics": topics or [],
        "decisions": decisions or [],
        "todos": todos or [],
        "pending_items": pending_items or [],
        "confirmations": confirmations or [],
        "changes_from_previous": changes_from_previous or [],
    }
    sections: list[dict] = []

    for key, title, text_field in _LEGACY_SECTION_MAP:
        rows = source.get(key) or []
        items: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get(text_field) or "").strip()
            if text:
                items.append({"text": text})
        if items:
            sections.append({"title": title, "items": items})

    todo_rows = source.get("todos") or []
    todo_items: list[dict] = []
    for row in todo_rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("task") or "").strip()
        if not text:
            continue
        item: dict = {"text": text}
        if row.get("owner"):
            item["owner"] = row["owner"]
        if row.get("deadline"):
            item["deadline"] = row["deadline"]
        todo_items.append(item)
    if todo_items:
        # 議題の直後に ToDo を差し込みたいが、簡易に末尾寄りでも可。決定の後に入れる。
        insert_at = len(sections)
        for i, sec in enumerate(sections):
            if sec["title"] == "決定事項":
                insert_at = i + 1
                break
        sections.insert(insert_at, {"title": "ToDo", "items": todo_items})

    return sections


def sections_from_snapshot(snapshot) -> list[dict]:
    """MinutesSnapshot から有効な sections を得る(レガシー互換込み)。"""
    sections = getattr(snapshot, "sections", None) or []
    if isinstance(sections, list) and len(sections) > 0:
        return sections
    return legacy_to_sections(
        topics=getattr(snapshot, "topics", None),
        decisions=getattr(snapshot, "decisions", None),
        todos=getattr(snapshot, "todos", None),
        pending_items=getattr(snapshot, "pending_items", None),
        confirmations=getattr(snapshot, "confirmations", None),
        changes_from_previous=getattr(snapshot, "changes_from_previous", None),
    )


def _merge_items(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged: list[dict] = []
    index_by_text: dict[str, int] = {}

    for item in existing:
        if not isinstance(item, dict):
            continue
        key = _normalize_key(item.get("text"))
        if key and key in index_by_text:
            merged[index_by_text[key]] = {**merged[index_by_text[key]], **item}
            continue
        if key:
            index_by_text[key] = len(merged)
        merged.append(dict(item))

    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = _normalize_key(item.get("text"))
        if key and key in index_by_text:
            merged[index_by_text[key]] = {**merged[index_by_text[key]], **item}
            continue
        if key:
            index_by_text[key] = len(merged)
        merged.append(dict(item))

    return merged


def merge_minutes(current: MinutesData, incoming: MinutesData) -> MinutesData:
    """LLM出力を既存まとめへマージし、既存セクション・項目の欠落を防ぐ。"""
    merged_sections: list[dict] = []
    index_by_title: dict[str, int] = {}

    for section in current.sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        items = section.get("items") if isinstance(section.get("items"), list) else []
        key = _normalize_key(title)
        if key and key in index_by_title:
            idx = index_by_title[key]
            merged_sections[idx]["items"] = _merge_items(
                merged_sections[idx].get("items") or [], items
            )
            continue
        entry = {"title": title or "無題", "items": [dict(i) for i in items if isinstance(i, dict)]}
        if key:
            index_by_title[key] = len(merged_sections)
        merged_sections.append(entry)

    for section in incoming.sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip() or "無題"
        items = section.get("items") if isinstance(section.get("items"), list) else []
        key = _normalize_key(title)
        if key and key in index_by_title:
            idx = index_by_title[key]
            merged_sections[idx]["items"] = _merge_items(
                merged_sections[idx].get("items") or [],
                [dict(i) for i in items if isinstance(i, dict)],
            )
            continue
        entry = {
            "title": title,
            "items": [dict(i) for i in items if isinstance(i, dict)],
        }
        if key:
            index_by_title[key] = len(merged_sections)
        merged_sections.append(entry)

    return MinutesData(sections=merged_sections)


def is_catastrophic_shrink(current: MinutesData, incoming: MinutesData) -> bool:
    """項目総数が大きく減った更新を異常とみなす。"""
    current_n = current.item_count()
    incoming_n = incoming.item_count()
    if current_n < 4:
        return False
    if incoming_n > 2:
        return False
    if incoming_n >= current_n:
        return False
    return incoming_n <= max(2, current_n // 2)


def _validate_minutes_json(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Qwen3の出力をJSONとして解析できませんでした: %s", raw[:200])
        return None

    if not isinstance(data, dict):
        return None
    sections = data.get("sections")
    if not isinstance(sections, list):
        logger.warning("Qwen3の出力に sections 配列がありません: %s", list(data.keys()))
        return None

    normalized: list[dict] = []
    for section in sections:
        if not isinstance(section, dict):
            logger.warning("sections の要素が辞書ではありません: %s", section)
            return None
        title = section.get("title")
        items = section.get("items")
        if not isinstance(title, str) or not title.strip():
            logger.warning("section.title が不正です: %s", section)
            return None
        if not isinstance(items, list):
            logger.warning("section.items が配列ではありません: %s", section)
            return None
        norm_items: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                logger.warning("item が辞書ではありません: %s", item)
                return None
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                logger.warning("item.text が不正です: %s", item)
                return None
            norm_items.append(dict(item))
        normalized.append({"title": title.strip(), "items": norm_items})

    return {"sections": normalized}


class MinutesGenerator:
    """Ollama上のQwen3モデルを呼び出し、まとめJSONを差分更新する。"""

    def __init__(self, host: str, model: str, max_retries: int = 1) -> None:
        self._client = ollama.Client(host=host)
        self._model = model
        self._max_retries = max_retries

    def update(
        self,
        current: MinutesData,
        new_transcript_text: str,
        summary_mode: str | None = None,
    ) -> MinutesData:
        """現在のまとめと新規発言テキストから、更新後のまとめを生成する。"""
        if not new_transcript_text.strip():
            return current

        mode = normalize_summary_mode(summary_mode)
        user_prompt = (
            "これまでのまとめ:\n"
            f"{json.dumps(current.to_dict(), ensure_ascii=False, indent=2)}\n\n"
            "新しい発言記録:\n"
            f"{new_transcript_text}\n"
        )

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.chat(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt_for_mode(mode)},
                        {"role": "user", "content": user_prompt},
                    ],
                    format="json",
                    options={"temperature": 0.2},
                )
            except Exception:
                logger.exception("Ollama呼び出しに失敗しました(attempt=%s)", attempt)
                continue

            content = response["message"]["content"]
            validated = _validate_minutes_json(content)
            if validated is None:
                logger.warning("まとめJSONの検証に失敗したため再試行します(attempt=%s)", attempt)
                continue

            incoming = MinutesData.from_dict(validated)
            if is_catastrophic_shrink(current, incoming):
                logger.warning(
                    "まとめの項目数が大幅に縮小したため更新を破棄します"
                    "(current=%s, incoming=%s, attempt=%s)",
                    current.item_count(),
                    incoming.item_count(),
                    attempt,
                )
                continue

            return merge_minutes(current, incoming)

        logger.error("まとめの更新に失敗したため、現在のまとめを保持します")
        return current

    def generate_final(
        self,
        current: MinutesData,
        full_corrected_transcript: str,
        summary_mode: str | None = None,
    ) -> MinutesData:
        """会議終了時、修正済み全文を用いて最終まとめを生成する。"""
        return self.update(current, full_corrected_transcript, summary_mode=summary_mode)
