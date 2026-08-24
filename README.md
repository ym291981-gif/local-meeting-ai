# リアルタイムAI議事録・文書活用支援ツール(Phase 1 MVP)

Zoom会議のPC内部音声を準リアルタイムで文字起こしし、話者を整理した「会議全文記録」と、
ローカルLLM(Qwen3)による「議事録」を、それぞれ独立したデータとして保存するツールです。

詳細な要件は [docs/requirements.md](docs/requirements.md) を参照してください。
開発中につまずいた点・工夫した点は
[docs/challenges-and-learnings.md](docs/challenges-and-learnings.md) にまとめています。

会議音声・文字起こし・議事録などの社内情報は外部へ送信せず、すべてローカルPC上で処理します
(Whisper / pyannote / Qwen3(Ollama)はすべてローカル実行)。

## 構成

```text
local-meeting-ai/
├── docs/requirements.md   要件定義書
├── backend/               FastAPIアプリ本体(Python)
│   ├── app/
│   │   ├── audio/         PC内部音声取得・チャンク化
│   │   ├── pipeline/      Whisper文字起こし・pyannote話者分離・Qwen3議事録生成
│   │   ├── api/           REST API・WebSocket
│   │   └── db/            SQLAlchemyモデル
│   └── tests/             pytestによる自動テスト
├── frontend/static/       ブラウザで表示するUI(素のHTML/CSS/JS、ビルド不要)
└── scripts/               動作確認・デモ用スクリプト(製品機能ではない)
```

## 必要な環境

- Windows 10/11
- Python 3.11
- NVIDIA GPU(推奨。CPUのみでも動作しますが処理速度が大幅に低下します)
- [Ollama for Windows](https://ollama.com/download)
- Zoom(本番利用時)

## セットアップ手順

### 1. Python仮想環境の作成・依存パッケージのインストール

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate

# GPU(CUDA)を使う場合は、先にCUDA対応のPyTorchを入れておく
# (pyannote.audioが依存するtorch/torchaudioがこの後インストールされるため)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

pip install -r requirements.txt
```

CPUのみで動かす場合は、上記のtorchインストール手順は不要です(`requirements.txt`の
インストール時にCPU版が自動的に入ります)。

### 2. 環境変数の設定

```powershell
copy .env.example .env
```

`.env` を開き、必要に応じて値を変更してください。特に以下は動作に必須です。

- `HF_TOKEN`: [Hugging Face](https://hf.co/settings/tokens) で発行したアクセストークン。
  事前に以下3つのモデルページで利用規約に同意しておく必要があります(いずれもログイン後、
  ページ内の同意フォームを送信するだけです)。
  - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
  - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
  - [pyannote/wespeaker-voxceleb-resnet34-LM](https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM)

  話者の横断クラスタリングには、分離パイプライン内蔵のWeSpeaker embeddingを使います
  (古い`pyannote/embedding`は使いません)。

  **注**: `pyannote/speaker-diarization-community-1`(最新モデル)はpyannote.audio 4.0系専用で、
  本プロジェクトが使う3.3系(VRAM急増バグ回避のため固定)では動作しないため、
  一世代前の`speaker-diarization-3.1`を採用しています。
- GPUがない場合は `WHISPER_DEVICE=cpu`, `DIARIZATION_DEVICE=cpu`, `WHISPER_COMPUTE_TYPE=int8` に変更してください。

### 3. Ollama側の準備

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Ollamaはインストール後、自動的にバックグラウンドで起動します
(`http://localhost:11434` でAPIが待機します)。

### 4. アプリの起動

いちばん簡単なのは、`scripts\start-app.bat` をダブルクリックすることです。
初回起動時にデスクトップへ「議事録アプリ」ショートカットも作ります。

- 黒い画面が開いたままなら起動中です。**この画面は閉じないでください**
- 少し待つとブラウザで `http://localhost:8000` が開きます
- 終わったら黒い画面を閉じるか、その画面で `Ctrl+C` を押します

コマンドで起ち上げる場合は次のとおりです。

```powershell
cd backend
.venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

ブラウザで `http://localhost:8000` を開くと画面が表示されます。「会議を開始」を押すと、
その瞬間からPC内部音声(既定の再生デバイスに流れている音声)の取得・文字起こし・
話者分離・議事録生成が始まります。

## 動作確認手順(要件定義書 第36.5章のStep1〜10に対応)

開発中は、以下のスクリプトで各段階を個別に確認できます(いずれも製品機能ではなく開発・検証用です)。

```powershell
cd backend
.venv\Scripts\activate

# Step1: PC内部音声を取得できるか(ループバックデバイス一覧の確認)
python ..\scripts\list_audio_devices.py

# Step1: 実際に10秒間録音してWAVへ保存できるか
python ..\scripts\record_sample.py --seconds 10 --out tests\fixtures\sample.wav

# Step2: 録音した音声をWhisperで文字起こしできるか
python ..\scripts\transcribe_wav.py --wav tests\fixtures\sample.wav
```

Step3〜9(リアルタイム表示・話者分離・議事録生成・保存)は、サーバーを起動してブラウザから
実際に会議を開始することで確認します。

### Step10: 固定デモ音声での通し確認

要件定義書 第30章のサンプル会議文をWindows標準の音声合成(SAPI5)で生成し、それを
再生しながら本番と同一の処理経路(内部音声取得→文字起こし→話者分離→議事録生成)が
動作することを確認します。

```powershell
# デモ音声を生成(初回のみ)
pip install pyttsx3
python ..\scripts\generate_demo_audio.py

# サーバーを別ターミナルで起動しておく
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 通し確認スクリプトを実行(サーバーへのAPI呼び出し + デモ音声再生を自動実行)
python ..\scripts\run_demo_e2e.py
```

**注意**: `generate_demo_audio.py` はPCにインストールされている音声合成ボイスを使うため、
1種類のボイスしかない場合は全発言が同じ声になります。この場合、文字起こし・議事録生成の
動作確認はできますが、話者分離(pyannote)の精度検証には向きません。より正確な検証を
行う場合は、複数人が実際に読み上げた音声を用意し、同様に再生して確認してください。

## 自動テスト

GPU・音声デバイス・Ollamaサーバーに依存しない範囲(チャンク処理・話者クラスタリングの
アルゴリズム・議事録JSON検証・API疎通)は、pytestで自動テストできます。

```powershell
cd backend
.venv\Scripts\activate
pytest
```

## 技術的な注意点・既知の制約

- **pyannote.audioのバージョン**: 4.0.x系の一部バージョンでVRAM使用量が急増する既知の
  不具合が報告されているため、`requirements.txt`では3.3.2系に固定しています。これに伴い、
  3.3系と互換性のない`pyannote/speaker-diarization-community-1`(最新モデル、4.0系専用)
  ではなく、一世代前の`pyannote/speaker-diarization-3.1`を話者分離モデルとして使用しています。
- **huggingface_hubのバージョン**: `pyannote.audio==3.3.2`は`use_auth_token`引数を使う
  古い`huggingface_hub`のAPIに依存しているため、これを廃止した1.0以降と組み合わせると
  `Pipeline.from_pretrained()`が失敗します。`requirements.txt`で`huggingface_hub==0.36.2`
  に固定しています。
- **speechbrainのWindows限定バグ**: 以前は`pyannote/embedding`(speechbrain依存)を
  別途読み込んでいましたが、現在はパイプライン内蔵のWeSpeakerを使います。
  念のため`app/pipeline/diarization.py`の起動時パッチは残しています。
- **話者クラスタリング**: 短い発話ごとに別IDを切ると同一人物が`speaker_01`〜
  `speaker_10`以上に分裂することがありました。チャンク内の同じローカル話者は
  1回だけ割り当て、既定の距離閾値は`0.65`です。`.env`の
  `SPEAKER_SIMILARITY_THRESHOLD`で調整できます。
  逆に、8秒程度のチャンクで自己紹介が連続すると別人を1人にまとめやすいです。
  開始画面の「話者数(任意)」か`.env`の`DIARIZATION_MIN_SPEAKERS`で人数を渡すと、
  pyannoteが分けやすくなります。人数不明のときは、文字起こし区間ごとの声の
  特徴でも再分割します。
- **WhisperとpyannoteのcuDNN競合(重要)**: Whisper(ctranslate2)とpyannote(torch)を
  両方`cuda`に設定すると、それぞれが同梱する`cuDNN`のバージョンが競合し、**Pythonの例外
  ではなくプロセスそのものがクラッシュする**既知の問題を確認しています。そのため
  `.env`では`WHISPER_DEVICE=cuda` / `DIARIZATION_DEVICE=cpu`の組み合わせを既定値としています。
  両方をcudaにしたい場合は、Whisperとpyannoteを別プロセスに分離するなどの対応が別途必要です。
- **VRAMが厳しい場合**: `.env`の`DIARIZATION_DEVICE=cpu`に変更することで、話者分離のみ
  CPUで実行できます(文字起こし・議事録生成はGPUのまま利用可能)。上記のcuDNN競合を
  避ける意味でも、既定では`cpu`を推奨します。
- **チャンク境界**: 固定時間でのチャンク分割時に発言が途切れる可能性を減らすため、
  無音区間を探して境界を調整する簡易VADを実装していますが、完全ではありません。
- **議事録生成の出力ゆらぎ**: Qwen3の出力がJSON形式から外れる場合、直前の議事録を
  保持したまま次回の更新を待ちます(一次情報を上書きしないという方針に合わせた挙動です)。
