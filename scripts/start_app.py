"""デスクトップから議事録アプリを起ち上げるランチャー。

サーバーを起動し、準備ができたらブラウザを開く。
このウィンドウを閉じるとサーバーも停止する。
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://localhost:{PORT}"
OLLAMA_URL = "http://127.0.0.1:11434/api/tags"
SHORTCUT_NAME = "議事録アプリ.lnk"


def _set_window_title(title: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)


def _pause(message: str) -> None:
    print()
    print(message)
    try:
        input("Enter キーで閉じます...")
    except EOFError:
        pass


def _port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def _ollama_running() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=1.5):
            return True
    except Exception:
        return False


def _open_browser_when_ready(timeout_seconds: float = 90.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _port_in_use():
            webbrowser.open(URL)
            return
        time.sleep(0.4)
    print(f"サーバーの起動待ちがタイムアウトしました。手動で {URL} を開いてください。")


def _ensure_desktop_shortcut() -> Path | None:
    bat_path = Path(__file__).resolve().parent / "start-app.bat"
    if not bat_path.exists():
        return None

    shortcut_name = SHORTCUT_NAME.replace("'", "''")
    bat = str(bat_path).replace("'", "''")
    workdir = str(bat_path.parent).replace("'", "''")
    icon = str(VENV_PYTHON if VENV_PYTHON.exists() else bat_path).replace("'", "''")
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        f"$path = Join-Path $desktop '{shortcut_name}'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        "$s = $ws.CreateShortcut($path); "
        f"$s.TargetPath = '{bat}'; "
        f"$s.WorkingDirectory = '{workdir}'; "
        f"$s.IconLocation = '{icon}'; "
        "$s.WindowStyle = 1; "
        "$s.Description = 'リアルタイムAI議事録を起動'; "
        "$s.Save(); "
        "Write-Output $path"
    )
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        created = completed.stdout.strip().splitlines()
        return Path(created[-1]) if created else None
    except Exception:
        return None


def main() -> int:
    _set_window_title("議事録アプリ")
    if "--shortcut-only" in sys.argv:
        shortcut = _ensure_desktop_shortcut()
        if shortcut is None:
            print("デスクトップショートカットを作成できませんでした。")
            return 1
        print(f"作成しました: {shortcut}")
        return 0
    print("=" * 48)
    print("  リアルタイムAI議事録")
    print("=" * 48)
    print()

    shortcut = _ensure_desktop_shortcut()
    if shortcut is not None:
        print(f"デスクトップのショートカット: {shortcut.name}")
        print()

    if not VENV_PYTHON.exists():
        print("初回セットアップがまだです。")
        print("README の「セットアップ手順」を先に実行してください。")
        _pause("仮想環境 (backend\\.venv) が見つかりません。")
        return 1

    if _port_in_use():
        print("すでに起動中です。ブラウザを開きます。")
        webbrowser.open(URL)
        _pause("このウィンドウは閉じて問題ありません。")
        return 0

    if _ollama_running():
        print("Ollama: 起動しています")
    else:
        print("Ollama: 応答がありません")
        print("  議事録の自動作成には Ollama が必要です。")
        print("  スタートメニューから Ollama を起ち上げてください。")
        print("  文字起こし画面そのものは、このまま使えます。")
        print()

    print("サーバーを起ち上げます。")
    print("この黒い画面は閉じないでください。閉じるとアプリが停止します。")
    print(f"ブラウザが開かないときは {URL} を開いてください。")
    print()

    opener = threading.Thread(target=_open_browser_when_ready, daemon=True)
    opener.start()

    try:
        completed = subprocess.run(
            [
                str(VENV_PYTHON),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                HOST,
                "--port",
                str(PORT),
            ],
            cwd=str(BACKEND_DIR),
        )
    except KeyboardInterrupt:
        print()
        print("停止しました。")
        return 0

    if completed.returncode != 0:
        _pause(f"サーバーが終了コード {completed.returncode} で停止しました。")
        return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
