"""pyannoteによる話者分離とオンライン話者クラスタリング
(要件定義書 第8.2章, 第17章, 第20章)。

pyannoteの診断はチャンク単位ではローカルなラベル(SPEAKER_00等)しか付与できないため、
以下の2段構成で会議全体を通じて一貫したSpeaker IDを維持する。

    1. DiarizationEngine.diarize_chunk()
       チャンク内の発話区間(ローカルな話者ラベル付き)とそのembeddingを検出する。
    2. SpeakerRegistry.assign()
       各発話区間のembeddingベクトルを、既知のSpeaker(embedding_centroid)と
       コサイン距離で比較し、閾値以内なら既存のspeaker_NNへ、閾値外なら新しい
       speaker_NNを発行して割り当てる(オンライン話者クラスタリング)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock

import numpy as np
import torch
from pyannote.audio import Inference, Model, Pipeline
from sqlalchemy.orm import Session

from app.db.models import Speaker

logger = logging.getLogger(__name__)

_MIN_TURN_SECONDS = 0.3


@dataclass
class DiarizedTurn:
    """チャンク内の相対時間(ms)で表した発話区間と、その音声embedding。"""

    start_ms: int
    end_ms: int
    local_label: str
    embedding: np.ndarray


class DiarizationEngine:
    """pyannoteのモデルを一度だけロードし、チャンク音声から発話区間+embeddingを抽出する。"""

    def __init__(
        self,
        device: str = "cuda",
        hf_token: str = "",
        embedding_batch_size: int = 4,
    ) -> None:
        self._device = device
        self._hf_token = hf_token or None
        self._embedding_batch_size = embedding_batch_size
        self._pipeline: Pipeline | None = None
        self._embedding_inference: Inference | None = None
        self._lock = Lock()

    def _ensure_loaded(self) -> None:
        if self._pipeline is not None:
            return
        logger.info("pyannote話者分離パイプラインを読み込みます: device=%s", self._device)
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1", token=self._hf_token
        )
        self._pipeline.to(torch.device(self._device))

        embedding_model = Model.from_pretrained("pyannote/embedding", use_auth_token=self._hf_token)
        embedding_model.to(torch.device(self._device))
        self._embedding_inference = Inference(embedding_model, window="whole")
        try:
            self._embedding_inference.batch_size = self._embedding_batch_size
        except Exception:  # pragma: no cover - Inferenceの実装差異に対する保険
            logger.debug("embedding_batch_sizeの設定に失敗しました(無視して続行)")

    def diarize_chunk(self, samples: np.ndarray, sample_rate: int) -> list[DiarizedTurn]:
        """1チャンク分の音声(float32, mono)から発話区間とembeddingを抽出する。"""
        if len(samples) == 0:
            return []

        self._ensure_loaded()
        assert self._pipeline is not None

        with self._lock:
            waveform = torch.from_numpy(samples).float().unsqueeze(0)
            diarization = self._pipeline({"waveform": waveform, "sample_rate": sample_rate})

            turns: list[DiarizedTurn] = []
            for segment, _, label in diarization.itertracks(yield_label=True):
                start_sample = int(segment.start * sample_rate)
                end_sample = int(segment.end * sample_rate)
                if (end_sample - start_sample) < int(_MIN_TURN_SECONDS * sample_rate):
                    continue
                clip = samples[start_sample:end_sample]
                embedding = self._extract_embedding(clip, sample_rate)
                if embedding is None:
                    continue
                turns.append(
                    DiarizedTurn(
                        start_ms=int(segment.start * 1000),
                        end_ms=int(segment.end * 1000),
                        local_label=str(label),
                        embedding=embedding,
                    )
                )
            return turns

    def _extract_embedding(self, clip: np.ndarray, sample_rate: int) -> np.ndarray | None:
        assert self._embedding_inference is not None
        waveform = torch.from_numpy(clip).float().unsqueeze(0)
        try:
            with torch.inference_mode():
                embedding = self._embedding_inference(
                    {"waveform": waveform, "sample_rate": sample_rate}
                )
        except Exception:
            logger.exception("embedding抽出に失敗しました。この区間はスキップします")
            return None
        return np.asarray(embedding, dtype=np.float32).reshape(-1)


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 1.0
    return 1.0 - float(np.dot(a, b) / denom)


class SpeakerRegistry:
    """会議単位で既存Speakerのembedding中心と比較し、Speaker DBレコードを
    作成・更新するオンライン話者クラスタリングレジストリ。

    話者統合(第20章)がされたSpeakerは merged_into_id が設定されるため、
    候補から除外し、統合先のSpeakerのみを比較対象とする。
    """

    def __init__(self, db: Session, meeting_id: int, similarity_threshold: float = 0.45) -> None:
        self._db = db
        self._meeting_id = meeting_id
        self._threshold = similarity_threshold

    def _active_speakers(self) -> list[Speaker]:
        speakers = (
            self._db.query(Speaker)
            .filter(Speaker.meeting_id == self._meeting_id, Speaker.merged_into_id.is_(None))
            .all()
        )
        return [s for s in speakers if s.embedding_centroid is not None]

    def _next_label(self) -> str:
        count = self._db.query(Speaker).filter(Speaker.meeting_id == self._meeting_id).count()
        return f"speaker_{count + 1:02d}"

    def assign(self, embedding: np.ndarray) -> Speaker:
        """embeddingに最も近い既存Speakerへ割り当てる。閾値内に一致がなければ新規発行する。"""
        candidates = self._active_speakers()
        best_speaker: Speaker | None = None
        best_distance = float("inf")
        for speaker in candidates:
            centroid = np.asarray(speaker.embedding_centroid, dtype=np.float32)
            distance = _cosine_distance(embedding, centroid)
            if distance < best_distance:
                best_distance = distance
                best_speaker = speaker

        if best_speaker is not None and best_distance <= self._threshold:
            centroid = np.asarray(best_speaker.embedding_centroid, dtype=np.float32)
            n = best_speaker.embedding_count
            new_centroid = (centroid * n + embedding) / (n + 1)
            best_speaker.embedding_centroid = new_centroid.tolist()
            best_speaker.embedding_count = n + 1
            self._db.add(best_speaker)
            self._db.commit()
            return best_speaker

        label = self._next_label()
        new_speaker = Speaker(
            meeting_id=self._meeting_id,
            label=label,
            display_label=label,
            embedding_centroid=embedding.tolist(),
            embedding_count=1,
        )
        self._db.add(new_speaker)
        self._db.commit()
        self._db.refresh(new_speaker)
        logger.info("新しい話者を検出しました: %s (meeting_id=%s)", label, self._meeting_id)
        return new_speaker
