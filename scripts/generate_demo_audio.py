"""Step10通し確認用: 要件定義書 第30章のサンプル会議文を音声合成し、
開発・検証用の固定デモ会議音声(WAV)を生成する。

このスクリプトの出力はあくまで「開発・検証用の固定デモ会議音声」(第5章)であり、
アプリ本体がファイルを直接読み込む機能ではない。生成したWAVは音声プレイヤーで
再生し、その再生音をPC内部音声としてアプリに取得させることで、本番と同一の
処理経路を検証する(第36.2章)。run_demo_e2e.py と組み合わせて使う。

注意: Windows標準のSAPI5音声合成を利用する。PCにインストールされている音声
(Voice)が1つしかない場合、全発言が同じ声になり話者分離(pyannote)の精度検証
には向かないが、文字起こし・議事録生成パイプライン自体の動作確認には利用できる。

実行方法:
    pip install pyttsx3
    python scripts\\generate_demo_audio.py
"""
from __future__ import annotations

import wave
from pathlib import Path

import pyttsx3

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures" / "demo_meeting.wav"
)

# 要件定義書 第30章のサンプル会議文
DEMO_LINES = [
    ("佐藤", "それではA案件について確認します。"),
    ("松島", "納期ですが、8月20日から8月27日に変更したいと思います。"),
    ("佐藤", "分かりました。では27日で進めましょう。"),
    ("鈴木", "資料の修正は私が担当します。25日までに対応します。"),
]

_SILENCE_SECONDS = 1.0


def _pick_voice_ids(engine: "pyttsx3.Engine", speaker_names: list[str]) -> dict[str, str]:
    voices = engine.getProperty("voices")
    if not voices:
        raise RuntimeError("利用可能な音声合成ボイスが見つかりませんでした")

    assigned: dict[str, str] = {}
    for i, name in enumerate(speaker_names):
        voice = voices[i % len(voices)]
        assigned[name] = voice.id
    return assigned


def _concatenate_with_silence(paths: list[Path], out_path: Path, silence_seconds: float) -> None:
    frames_list = []
    params = None
    for path in paths:
        with wave.open(str(path), "rb") as wf:
            if params is None:
                params = wf.getparams()
            frames_list.append(wf.readframes(wf.getnframes()))

    assert params is not None
    silence_frames = (
        b"\x00" * int(params.framerate * params.sampwidth * params.nchannels * silence_seconds)
    )

    with wave.open(str(out_path), "wb") as out_wf:
        out_wf.setparams(params)
        for i, frames in enumerate(frames_list):
            out_wf.writeframes(frames)
            if i != len(frames_list) - 1:
                out_wf.writeframes(silence_frames)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    engine = pyttsx3.init()
    speaker_names = sorted({name for name, _ in DEMO_LINES})
    voice_by_speaker = _pick_voice_ids(engine, speaker_names)
    if len({v for v in voice_by_speaker.values()}) == 1:
        print("警告: 利用可能な音声ボイスが1種類のみのため、全話者が同じ声になります。")
        print("      文字起こし・議事録生成の動作確認は可能ですが、話者分離の精度検証には不向きです。")

    segment_paths: list[Path] = []
    print("デモ会議音声を生成します:")
    for idx, (speaker, text) in enumerate(DEMO_LINES):
        engine.setProperty("voice", voice_by_speaker[speaker])
        segment_path = OUTPUT_PATH.parent / f"_segment_{idx}.wav"
        engine.save_to_file(text, str(segment_path))
        engine.runAndWait()
        segment_paths.append(segment_path)
        print(f"  [{speaker}] {text}")

    _concatenate_with_silence(segment_paths, OUTPUT_PATH, _SILENCE_SECONDS)

    for path in segment_paths:
        path.unlink(missing_ok=True)

    print(f"\nデモ音声を生成しました: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
