"""Step10通し確認: 固定デモ音声を再生しながら、起動中のアプリサーバーに対して
「会議開始 -> デモ音声再生(PC内部音声として取得) -> 会議終了」の一連の流れを
自動実行する統合確認スクリプト(要件定義書 第31章 方式B)。

事前に別ターミナルでサーバーを起動しておくこと:
    cd backend
    uvicorn app.main:app --host 0.0.0.0 --port 8000

さらに generate_demo_audio.py でデモ音声を用意しておくこと。

実行方法:
    python scripts\\run_demo_e2e.py
"""
from __future__ import annotations

import argparse
import time
import wave
import winsound
from pathlib import Path

import requests


def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--wav",
        type=str,
        default=str(Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures" / "demo_meeting.wav"),
    )
    parser.add_argument("--base-url", type=str, default="http://localhost:8000")
    parser.add_argument("--tail-wait-seconds", type=float, default=20.0)
    args = parser.parse_args()

    wav_path = Path(args.wav)
    if not wav_path.exists():
        raise SystemExit(
            f"デモ音声が見つかりません: {wav_path}\n先に generate_demo_audio.py を実行してください"
        )

    print("会議を開始します...")
    resp = requests.post(f"{args.base_url}/api/meetings", json={"title": "デモ会議(第30章)"})
    resp.raise_for_status()
    meeting = resp.json()
    meeting_id = meeting["id"]
    print(f"  meeting_id = {meeting_id}")

    # 内部音声キャプチャ・チャンク処理の初期化に少し時間がかかるため、再生前に待機する
    time.sleep(2.0)

    duration = _wav_duration_seconds(wav_path)
    print(f"デモ音声を再生します(約{duration:.1f}秒)。この音声がPC内部音声として取得されます...")
    winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)

    print(f"再生完了。パイプラインの処理遅延を考慮し{args.tail_wait_seconds}秒待機します...")
    time.sleep(args.tail_wait_seconds)

    print("会議を終了します(最終議事録を生成しています。数十秒かかる場合があります)...")
    resp = requests.post(f"{args.base_url}/api/meetings/{meeting_id}/stop", timeout=300)
    resp.raise_for_status()

    transcript = requests.get(f"{args.base_url}/api/meetings/{meeting_id}/transcript").json()
    print("\n=== 文字起こし結果(全文記録) ===")
    for u in transcript:
        speaker = u.get("speaker_label") or "話者未確定"
        print(f"[{u['start_ms'] / 1000:6.1f}s] ({speaker}) {u['effective_text']}")

    minutes_resp = requests.get(f"{args.base_url}/api/meetings/{meeting_id}/minutes/latest")
    print("\n=== 最終まとめ ===")
    if minutes_resp.status_code == 200:
        minutes = minutes_resp.json()
        for section in minutes.get("sections") or []:
            print(f"## {section.get('title')}")
            for item in section.get("items") or []:
                text = item.get("text", "")
                extras = []
                if item.get("owner"):
                    extras.append(f"担当: {item['owner']}")
                if item.get("deadline"):
                    extras.append(f"期限: {item['deadline']}")
                suffix = f" ({', '.join(extras)})" if extras else ""
                print(f"  - {text}{suffix}")
    else:
        print("まとめが生成されませんでした(発言が検出されなかった可能性があります)")

    print(
        "\n期待結果(要件定義書 第30章)との比較:\n"
        "  議題: A案件の納期\n"
        "  決定事項: 納期を8月20日から8月27日に変更する\n"
        "  ToDo: 資料を修正する(担当: 鈴木, 期限: 8月25日)"
    )


if __name__ == "__main__":
    main()
