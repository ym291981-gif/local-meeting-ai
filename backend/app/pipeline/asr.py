"""faster-whisperによる音声認識ラッパー(要件定義書 第8.1章 Whisper)。

Whisperは「何を言ったか」の判断のみを担当し(第9.1章)、話者分離やニュアンスの
要約は行わない。可能な限り発言をそのまま文字化する(第14章)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


@dataclass
class TranscribedSegment:
    start_ms: int
    end_ms: int
    text: str


class WhisperTranscriber:
    """faster-whisperモデルを一度だけロードし、チャンク音声を文字起こしする。"""

    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        device: str = "cuda",
        compute_type: str = "int8_float16",
        language: str = "ja",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model: WhisperModel | None = None
        self._lock = Lock()

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            logger.info(
                "Whisperモデルを読み込みます: model=%s device=%s compute_type=%s",
                self._model_name,
                self._device,
                self._compute_type,
            )
            self._model = WhisperModel(
                self._model_name, device=self._device, compute_type=self._compute_type
            )
        return self._model

    def transcribe_chunk(
        self, samples: np.ndarray, sample_rate: int, chunk_start_ms: int
    ) -> list[TranscribedSegment]:
        """1チャンク分の音声(float32, mono, 16kHz)を文字起こしする。

        戻り値のstart_ms/end_msはチャンク先頭からの相対時間ではなく、
        会議開始からの絶対時間(chunk_start_msを加算済み)とする。
        """
        if sample_rate != 16000:
            raise ValueError(f"Whisperには16kHzの音声が必要です(受信: {sample_rate}Hz)")
        if len(samples) == 0:
            return []

        model = self._ensure_model()
        with self._lock:
            segments, _info = model.transcribe(
                samples,
                language=self._language,
                vad_filter=True,
                beam_size=5,
            )
            results: list[TranscribedSegment] = []
            for seg in segments:
                text = seg.text.strip()
                if not text:
                    continue
                results.append(
                    TranscribedSegment(
                        start_ms=chunk_start_ms + int(seg.start * 1000),
                        end_ms=chunk_start_ms + int(seg.end * 1000),
                        text=text,
                    )
                )
            return results
