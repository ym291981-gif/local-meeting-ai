"""Audio chunker module: splits captured audio frames into fixed-duration
chunks and resamples them to 16kHz mono for Whisper/pyannote.

See docs/requirements.md section 16 for the near-real-time processing policy.
A naive fixed-time cut can slice a word in half, so this module searches for
a low-energy (near-silence) point around the target cut position to use as
the chunk boundary, reducing mid-word cuts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.signal import resample_poly

logger = logging.getLogger(__name__)

# How far around the target cut point to search for a near-silent point.
_SILENCE_SEARCH_WINDOW_SEC = 1.0
_SILENCE_FRAME_SEC = 0.02


@dataclass
class AudioChunk:
    start_ms: int
    end_ms: int
    samples: np.ndarray  # float32, mono, target_sample_rate
    sample_rate: int


def _to_mono(frames: np.ndarray) -> np.ndarray:
    if frames.ndim == 1:
        return frames
    return frames.mean(axis=1).astype(np.float32)


def resample_audio(mono: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Resample mono audio to the target sample rate (public helper, usable from scripts too)."""
    if source_rate == target_rate:
        return mono.astype(np.float32)
    gcd = np.gcd(source_rate, target_rate)
    up = target_rate // gcd
    down = source_rate // gcd
    resampled = resample_poly(mono, up, down)
    return resampled.astype(np.float32)


def _find_cut_index(mono: np.ndarray, target_index: int, sample_rate: int) -> int:
    """Find the sample index near target_index with the lowest RMS energy.

    Falls back to target_index if no clear low-energy point is found.
    """
    window = int(_SILENCE_SEARCH_WINDOW_SEC * sample_rate)
    frame = max(int(_SILENCE_FRAME_SEC * sample_rate), 1)
    lo = max(target_index - window, frame)
    hi = min(target_index + window, len(mono) - frame)
    if hi <= lo:
        return target_index

    best_index = target_index
    best_energy = float("inf")
    for start in range(lo, hi, frame):
        segment = mono[start : start + frame]
        energy = float(np.sqrt(np.mean(segment.astype(np.float64) ** 2)))
        if energy < best_energy:
            best_energy = energy
            best_index = start
    return best_index


class AudioChunker:
    """Buffers incoming audio frames and yields fixed-duration AudioChunks.

    Because cut points are searched within a window around the target
    position, the buffer must contain "target chunk length + search window"
    worth of samples before a cut is attempted.
    """

    def __init__(
        self,
        source_sample_rate: int,
        chunk_seconds: float,
        target_sample_rate: int = 16000,
    ) -> None:
        self._source_sample_rate = source_sample_rate
        self._chunk_seconds = chunk_seconds
        self._target_sample_rate = target_sample_rate
        self._lookahead_samples = int(_SILENCE_SEARCH_WINDOW_SEC * source_sample_rate)
        self._buffer = np.zeros(0, dtype=np.float32)
        self._elapsed_source_samples = 0  # samples already cut out so far (for start time calc)

    def feed(self, frames: np.ndarray) -> list[AudioChunk]:
        """Feed newly captured audio frames; returns any chunks now ready to be cut."""
        mono = _to_mono(frames)
        self._buffer = np.concatenate([self._buffer, mono])

        chunks: list[AudioChunk] = []
        target_samples = int(self._chunk_seconds * self._source_sample_rate)

        while len(self._buffer) >= target_samples + self._lookahead_samples:
            cut_index = max(_find_cut_index(self._buffer, target_samples, self._source_sample_rate), 1)

            segment = self._buffer[:cut_index]
            self._buffer = self._buffer[cut_index:]

            start_ms = int(self._elapsed_source_samples / self._source_sample_rate * 1000)
            self._elapsed_source_samples += cut_index
            end_ms = int(self._elapsed_source_samples / self._source_sample_rate * 1000)

            resampled = resample_audio(segment, self._source_sample_rate, self._target_sample_rate)
            chunks.append(
                AudioChunk(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    samples=resampled,
                    sample_rate=self._target_sample_rate,
                )
            )
        return chunks

    def flush(self) -> AudioChunk | None:
        """Return any remaining buffered audio as a final chunk (e.g. at meeting end)."""
        if len(self._buffer) == 0:
            return None
        start_ms = int(self._elapsed_source_samples / self._source_sample_rate * 1000)
        self._elapsed_source_samples += len(self._buffer)
        end_ms = int(self._elapsed_source_samples / self._source_sample_rate * 1000)
        resampled = resample_audio(self._buffer, self._source_sample_rate, self._target_sample_rate)
        self._buffer = np.zeros(0, dtype=np.float32)
        return AudioChunk(
            start_ms=start_ms, end_ms=end_ms, samples=resampled, sample_rate=self._target_sample_rate
        )
