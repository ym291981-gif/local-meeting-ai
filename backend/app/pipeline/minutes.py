"""Ollama経由でQwen3を呼び出し、議事録を構造化データとして生成・更新する
(要件定義書 第8.3章 Qwen3, 第23〜24章, 第26章 差分更新方式)。

長時間会議の全文を毎回渡すのではなく、「現在の議事録」+「直近の新規発言」だけを
渡して更新後の議事録を得る差分更新方式を採用する。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import ollama

logger = logging.getLogger(__name__)

_EMPTY_MINUTES: dict = {
    "topics": [],
    "decisions": [],
    "todos": [],
    "pending_items": [],
    "confirmations": [],
    "changes_from_previous": [],
}

_REQUIRED_KEYS = tuple(_EMPTY_MINUTES.keys())

_SYSTEM_PROMPT = """あなたは日本語の会議の議事録整理を行うアシスタントです。
与えられた「これまでの議事録(JSON)」と「新しい発言記録」から、議事録を更新してください。

出力は必ず次のキーを持つJSONオブジェクトのみとしてください(説明文や前置きは不要):
- topics: [{"title": "議題名"}]
- decisions: [{"text": "決定事項"}]
- todos: [{"task": "作業内容", "owner": "担当者名 or null", "deadline": "期限(YYYY-MM-DD等) or null"}]
- pending_items: [{"text": "保留事項"}]
- confirmations: [{"text": "確認事項"}]
- changes_from_previous: [{"text": "前回からの変更点"}]

ルール:
- 既存の議事録の内容は、新しい発言と矛盾しない限り保持してください。
- 新しい発言に含まれる情報のみ追加・更新し、憶測で情報を作らないでください。
- 発言中の細かな言い回しではなく、内容を整理して記載してください。
"""


@dataclass
class MinutesData:
    topics: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    todos: list[dict] = field(default_factory=list)
    pending_items: list[dict] = field(default_factory=list)
    confirmations: list[dict] = field(default_factory=list)
    changes_from_previous: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topics": self.topics,
            "decisions": self.decisions,
            "todos": self.todos,
            "pending_items": self.pending_items,
            "confirmations": self.confirmations,
            "changes_from_previous": self.changes_from_previous,
        }

    @classmethod
    def empty(cls) -> "MinutesData":
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "MinutesData":
        return cls(**{key: data.get(key, []) for key in _REQUIRED_KEYS})


def _validate_minutes_json(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Qwen3の出力をJSONとして解析できませんでした: %s", raw[:200])
        return None

    if not isinstance(data, dict):
        return None
    if not all(key in data and isinstance(data[key], list) for key in _REQUIRED_KEYS):
        logger.warning("Qwen3の出力に必要なキーが不足しています: %s", list(data.keys()))
        return None
    # 各キーの値は辞書のリストであることを期待している(例: [{"text": "..."}])。
    # Qwen3が稀に文字列のリスト等を返すことがあるため、ここで型を検証し、
    # 期待と異なる場合はJSON全体を不正とみなして呼び出し元にリトライ/保持させる。
    for key in _REQUIRED_KEYS:
        if not all(isinstance(item, dict) for item in data[key]):
            logger.warning(
                "Qwen3の出力の'%s'に辞書以外の要素が含まれています: %s", key, data[key]
            )
            return None
    return data


class MinutesGenerator:
    """Ollama上のQwen3モデルを呼び出し、議事録JSONを差分更新する。"""

    def __init__(self, host: str, model: str, max_retries: int = 1) -> None:
        self._client = ollama.Client(host=host)
        self._model = model
        self._max_retries = max_retries

    def update(self, current: MinutesData, new_transcript_text: str) -> MinutesData:
        """現在の議事録と新規発言テキストから、更新後の議事録を生成する。

        LLMの出力が不正な場合は現在の議事録をそのまま返す(要件定義書の
        「前回議事録を上書きしない」という一次情報保護方針に倣う)。
        """
        if not new_transcript_text.strip():
            return current

        user_prompt = (
            "これまでの議事録:\n"
            f"{json.dumps(current.to_dict(), ensure_ascii=False, indent=2)}\n\n"
            "新しい発言記録:\n"
            f"{new_transcript_text}\n"
        )

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.chat(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
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
            if validated is not None:
                return MinutesData.from_dict(validated)

            logger.warning("議事録JSONの検証に失敗したため再試行します(attempt=%s)", attempt)

        logger.error("議事録の更新に失敗したため、現在の議事録を保持します")
        return current

    def generate_final(self, current: MinutesData, full_corrected_transcript: str) -> MinutesData:
        """会議終了時、修正済み全文を用いて最終議事録を生成する(要件定義書 第27章)。"""
        return self.update(current, full_corrected_transcript)
