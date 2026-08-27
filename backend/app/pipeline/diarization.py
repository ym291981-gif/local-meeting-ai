"""pyannoteによる話者分離とオンライン話者クラスタリング
(要件定義書 第8.2章, 第17章, 第20章)。

pyannoteの診断はチャンク単位ではローカルなラベル(SPEAKER_00等)しか付与できないため、
以下の2段構成で会議全体を通じて一貫したSpeaker IDを維持する。

    1. DiarizationEngine.diarize_chunk()
       チャンク内の発話区間を検出し、ローカル話者ごとに1つのembeddingを付ける。
       embeddingはパイプライン内蔵のWeSpeaker(pyannote/wespeaker-voxceleb-resnet34-LM)
       から取得する。短いクリップごとに古いpyannote/embeddingを回さない。
    2. assign_turns() / speakers_for_segments() + SpeakerRegistry.assign()
       チャンク内の同じローカルラベルは原則1回だけクラスタリングする。
       ただし8秒チャンクではpyannoteが別人を1人にまとめやすいので、
       ローカル話者が1人しかいない場合はWhisper区間ごとのembeddingで再割当する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock

import numpy as np
import torch
from sqlalchemy.orm import Session

from app.db.models import Speaker

logger = logging.getLogger(__name__)


def _patch_speechbrain_windows_lazy_import() -> None:
    """speechbrainのLazyModule判定処理はUnix専用パス判定("/inspect.py"で終わるか)
    のため、Windowsではinspectモジュールからの内部プローブを誤って実インポートと
    判定してしまい、未インストールの任意依存(k2)を要求するImportErrorで落ちる
    既知の不具合(speechbrain側で修正PR提出済み・未リリース)がある。
    ここではその判定処理だけをクロスプラットフォーム対応版に置き換える。
    """
    try:
        import os as _os

        from speechbrain.utils import importutils as _sb_importutils

        _original_ensure_module = _sb_importutils.LazyModule.ensure_module

        def _patched_ensure_module(self, stacklevel: int):
            import inspect as _inspect
            import sys as _sys

            importer_frame = None
            try:
                importer_frame = _inspect.getframeinfo(_sys._getframe(stacklevel + 1))
            except AttributeError:
                pass

            if importer_frame is not None and _os.path.basename(
                importer_frame.filename
            ) == "inspect.py":
                raise AttributeError()

            if self.lazy_module is None:
                import importlib as _importlib

                try:
                    if self.package is None:
                        self.lazy_module = _importlib.import_module(self.target)
                    else:
                        self.lazy_module = _importlib.import_module(
                            f".{self.target}", self.package
                        )
                except Exception as e:  # noqa: BLE001
                    raise ImportError(f"Lazy import of {self!r} failed") from e

            return self.lazy_module

        _sb_importutils.LazyModule.ensure_module = _patched_ensure_module
        logger.debug(
            "speechbrainのLazyModule判定処理をWindows対応版に置き換えました "
            "(original=%s)",
            _original_ensure_module,
        )
    except Exception:  # noqa: BLE001 - パッチ失敗時は元の挙動のまま続行する
        logger.debug("speechbrainのWindows向けパッチ適用に失敗しました(無視して続行)")


_patch_speechbrain_windows_lazy_import()

from pyannote.audio import Pipeline  # noqa: E402

_MIN_TURN_SECONDS = 0.3
_MIN_EMBEDDING_SECONDS = 0.5
# speaker-diarization-3.1 のクラスタ閾値は約0.70。オンライン(貪欲)割当は
# 別人の誤結合を少し抑えるため、やや厳しめの0.65を既定にする。
DEFAULT_SIMILARITY_THRESHOLD = 0.65


@dataclass
class DiarizedTurn:
    """チャンク内の相対時間(ms)で表した発話区間と、その音声embedding。"""

    start_ms: int
    end_ms: int
    local_label: str
    embedding: np.ndarray


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    """L2正規化する。ゼロベクトルはそのまま返す。"""
    vec = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm == 0.0:
        return vec
    return (vec / norm).astype(np.float32)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """L2正規化済みベクトル同士のコサイン距離(0=同一, 2=正反対)。"""
    a_n = l2_normalize(a)
    b_n = l2_normalize(b)
    denom = float(np.linalg.norm(a_n) * np.linalg.norm(b_n))
    if denom == 0.0:
        return 1.0
    similarity = float(np.dot(a_n, b_n) / denom)
    similarity = max(-1.0, min(1.0, similarity))
    return 1.0 - similarity


def resolve_max_speakers(*values: int | None) -> int | None:
    """2人以上のヒントだけを会議全体の話者上限として使う。1以下・未指定は自動推定。"""
    hints = [value for value in values if value is not None and value >= 2]
    return max(hints) if hints else None


def resolve_min_speakers(*values: int | None) -> int | None:
    """互換用エイリアス。会議全体の話者上限を返す。"""
    return resolve_max_speakers(*values)


def assign_turns(registry: SpeakerRegistry, turns: list[DiarizedTurn]) -> list[Speaker]:
    """各区間へSpeakerを割り当てる。

    同じローカルラベルは原則まとめ、embeddingが大きく違う区間だけ独立に割当する。
    短いチャンクでpyannoteが別人を同一ラベルにしたケース向け。
    """
    assigned: list[Speaker] = []
    first_of_label: dict[str, Speaker] = {}
    for turn in turns:
        first = first_of_label.get(turn.local_label)
        if first is not None:
            distance = cosine_distance(
                turn.embedding, np.asarray(first.embedding_centroid, dtype=np.float32)
            )
            if distance <= registry.threshold:
                assigned.append(first)
                continue
            logger.info(
                "同一ローカル話者%sを分割します: distance=%.3f threshold=%.3f",
                turn.local_label,
                distance,
                registry.threshold,
            )
        speaker = registry.assign(turn.embedding)
        first_of_label.setdefault(turn.local_label, speaker)
        assigned.append(speaker)
    return assigned


def assign_local_labels(
    registry: SpeakerRegistry, turns: list[DiarizedTurn]
) -> dict[str, Speaker]:
    """チャンク内の同じローカルラベルは1回だけ SpeakerRegistry に渡す。"""
    speakers = assign_turns(registry, turns)
    mapping: dict[str, Speaker] = {}
    for turn, speaker in zip(turns, speakers, strict=True):
        mapping.setdefault(turn.local_label, speaker)
    return mapping


def speakers_for_segments(
    registry: SpeakerRegistry,
    segments: list,
    turns: list[DiarizedTurn],
    embed_segment,
) -> list[Speaker | None]:
    """Whisper区間ごとにSpeakerを決める。

    pyannoteが2人以上に分けられていれば区間の重なりで割当する。
    文字起こしと重ならない区間(ノイズ・BGM等)には Speaker 行を作らない。
    1人にまとめられている(または失敗している)ときは、文字起こし区間の
    embeddingで再クラスタリングする。
    """
    local_labels = {turn.local_label for turn in turns}
    if len(local_labels) >= 2:
        overlapping: list[DiarizedTurn] = []
        seen: set[int] = set()
        for segment in segments:
            best = _best_overlap_turn(segment, turns)
            if best is None:
                continue
            key = id(best)
            if key in seen:
                continue
            seen.add(key)
            overlapping.append(best)
        turn_speakers = assign_turns(registry, overlapping) if overlapping else []
        by_id = {
            id(turn): speaker
            for turn, speaker in zip(overlapping, turn_speakers, strict=True)
        }
        result: list[Speaker | None] = []
        for segment in segments:
            best = _best_overlap_turn(segment, turns)
            result.append(by_id.get(id(best)) if best is not None else None)
        return result

    result = []
    previous: Speaker | None = None
    for segment in segments:
        embedding = embed_segment(segment)
        if embedding is None:
            result.append(previous)
            continue
        previous = registry.assign(embedding)
        result.append(previous)
    return result


def _best_overlap_turn(segment, turns: list[DiarizedTurn]) -> DiarizedTurn | None:
    best: DiarizedTurn | None = None
    best_overlap = 0
    for turn in turns:
        overlap = max(0, min(segment.end_ms, turn.end_ms) - max(segment.start_ms, turn.start_ms))
        if overlap > best_overlap:
            best_overlap = overlap
            best = turn
    return best


def slice_audio(
    samples: np.ndarray, sample_rate: int, chunk_start_ms: int, start_ms: int, end_ms: int
) -> np.ndarray:
    """会議絶対時間の区間を、チャンク音声から切り出す。"""
    rel_start = (start_ms - chunk_start_ms) / 1000.0
    rel_end = (end_ms - chunk_start_ms) / 1000.0
    begin = max(0, int(rel_start * sample_rate))
    finish = min(len(samples), int(rel_end * sample_rate))
    if finish <= begin:
        return samples[0:0]
    return samples[begin:finish]


class DiarizationEngine:
    """pyannoteのモデルを一度だけロードし、チャンク音声から発話区間+embeddingを抽出する。"""

    def __init__(
        self,
        device: str = "cpu",
        hf_token: str = "",
        embedding_batch_size: int = 4,
    ) -> None:
        self._device = device
        self._hf_token = hf_token or None
        self._embedding_batch_size = embedding_batch_size
        self._pipeline: Pipeline | None = None
        self._lock = Lock()

    def _ensure_loaded(self) -> None:
        if self._pipeline is not None:
            return
        logger.info("pyannote話者分離パイプラインを読み込みます: device=%s", self._device)
        # 注: pyannote/speaker-diarization-community-1はpyannote.audio 4.0系専用のため、
        # VRAM急増バグを避けて3.3系に固定している本プロジェクトでは使用できない。
        # 3.3系と互換性のあるspeaker-diarization-3.1を使用する。
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=self._hf_token
        )
        self._pipeline.to(torch.device(self._device))
        if hasattr(self._pipeline, "embedding_batch_size"):
            self._pipeline.embedding_batch_size = self._embedding_batch_size
        logger.info(
            "話者embeddingはパイプライン内蔵のWeSpeakerを使用します"
            " (pyannote/embedding は使いません)"
        )

    def diarize_chunk(
        self,
        samples: np.ndarray,
        sample_rate: int,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[DiarizedTurn]:
        """1チャンク分の音声(float32, mono)から発話区間とembeddingを抽出する。

        ローカル話者の代表embeddingに加え、十分な長さの区間では区間ごとの
        embeddingも取る。短いチャンクで別人を1ラベルにまとめた場合の再分割用。
        """
        if len(samples) == 0:
            return []

        self._ensure_loaded()
        assert self._pipeline is not None

        pipeline_kwargs: dict = {"return_embeddings": True}
        if min_speakers is not None and min_speakers >= 2:
            pipeline_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None and max_speakers >= 2:
            pipeline_kwargs["max_speakers"] = max_speakers

        with self._lock:
            waveform = torch.from_numpy(np.ascontiguousarray(samples)).float().unsqueeze(0)
            output = self._pipeline(
                {"waveform": waveform, "sample_rate": sample_rate},
                **pipeline_kwargs,
            )
            if isinstance(output, tuple):
                diarization, embeddings = output
            else:
                diarization, embeddings = output, None

            label_to_embedding = _embeddings_by_label(diarization, embeddings)

            turns: list[DiarizedTurn] = []
            for segment, _, label in diarization.itertracks(yield_label=True):
                start_sample = int(segment.start * sample_rate)
                end_sample = int(segment.end * sample_rate)
                if (end_sample - start_sample) < int(_MIN_TURN_SECONDS * sample_rate):
                    continue
                key = str(label)
                embedding = label_to_embedding.get(key)
                clip = samples[start_sample:end_sample]
                clip_embedding = self._extract_clip_embedding(clip, sample_rate)
                if clip_embedding is not None:
                    embedding = clip_embedding
                elif embedding is None:
                    continue
                else:
                    label_to_embedding[key] = embedding
                turns.append(
                    DiarizedTurn(
                        start_ms=int(segment.start * 1000),
                        end_ms=int(segment.end * 1000),
                        local_label=key,
                        embedding=embedding,
                    )
                )
            local_labels = sorted({turn.local_label for turn in turns})
            logger.info(
                "話者分離結果: duration=%.1fs local_speakers=%s turns=%d "
                "min_speakers=%s max_speakers=%s",
                len(samples) / sample_rate,
                local_labels or ["(none)"],
                len(turns),
                min_speakers,
                max_speakers,
            )
            return turns

    def embed_clip(self, clip: np.ndarray, sample_rate: int) -> np.ndarray | None:
        """区間音声から話者embeddingを取る。短い区間はNone。"""
        self._ensure_loaded()
        with self._lock:
            return self._extract_clip_embedding(clip, sample_rate)

    def _extract_clip_embedding(self, clip: np.ndarray, sample_rate: int) -> np.ndarray | None:
        """パイプラインが代表embeddingを返せなかった区間向けのフォールバック。"""
        if len(clip) < int(_MIN_EMBEDDING_SECONDS * sample_rate):
            return None
        embedding_fn = getattr(self._pipeline, "_embedding", None)
        if embedding_fn is None:
            return None
        waveform = torch.from_numpy(np.ascontiguousarray(clip)).float().view(1, 1, -1)
        try:
            with torch.inference_mode():
                embedding = embedding_fn(waveform)
        except Exception:
            logger.exception("embedding抽出に失敗しました。この区間はスキップします")
            return None
        vec = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if not np.isfinite(vec).all() or float(np.linalg.norm(vec)) == 0.0:
            return None
        return l2_normalize(vec)


def _embeddings_by_label(diarization, embeddings) -> dict[str, np.ndarray]:
    """annotation.labels() の順に並んだ代表embeddingを、ラベル文字列へ対応付ける。"""
    mapping: dict[str, np.ndarray] = {}
    if embeddings is None:
        return mapping
    labels = list(diarization.labels())
    for index, label in enumerate(labels):
        if index >= len(embeddings):
            break
        vec = np.asarray(embeddings[index], dtype=np.float32).reshape(-1)
        if not np.isfinite(vec).all() or float(np.linalg.norm(vec)) == 0.0:
            continue
        mapping[str(label)] = l2_normalize(vec)
    return mapping


class SpeakerRegistry:
    """会議単位で既存Speakerのembedding中心と比較し、Speaker DBレコードを
    作成・更新するオンライン話者クラスタリングレジストリ。

    話者統合(第20章)がされたSpeakerは merged_into_id が設定されるため、
    候補から除外し、統合先のSpeakerのみを比較対象とする。
    """

    def __init__(
        self,
        db: Session,
        meeting_id: int,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        max_speakers: int | None = None,
    ) -> None:
        self._db = db
        self._meeting_id = meeting_id
        self._threshold = similarity_threshold
        self._max_speakers = max_speakers if max_speakers is not None and max_speakers >= 2 else None

    @property
    def threshold(self) -> float:
        return self._threshold

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

    def _at_capacity(self, candidate_count: int) -> bool:
        return self._max_speakers is not None and candidate_count >= self._max_speakers

    def _bind_to_speaker(self, speaker: Speaker, embedding: np.ndarray) -> Speaker:
        centroid = l2_normalize(np.asarray(speaker.embedding_centroid, dtype=np.float32))
        n = speaker.embedding_count
        new_centroid = l2_normalize((centroid * n + embedding) / (n + 1))
        speaker.embedding_centroid = new_centroid.tolist()
        speaker.embedding_count = n + 1
        self._db.add(speaker)
        self._db.commit()
        return speaker

    def assign(self, embedding: np.ndarray) -> Speaker:
        """embeddingに最も近い既存Speakerへ割り当てる。閾値内に一致がなければ新規発行する。

        会議全体の話者上限に達しているときは、距離が閾値を超えていても最近傍へ割当する。
        """
        embedding = l2_normalize(embedding)
        candidates = self._active_speakers()
        best_speaker: Speaker | None = None
        best_distance = float("inf")
        for speaker in candidates:
            centroid = np.asarray(speaker.embedding_centroid, dtype=np.float32)
            distance = cosine_distance(embedding, centroid)
            if distance < best_distance:
                best_distance = distance
                best_speaker = speaker

        at_cap = self._at_capacity(len(candidates))
        if best_speaker is not None and (best_distance <= self._threshold or at_cap):
            if at_cap and best_distance > self._threshold:
                logger.info(
                    "話者上限(%s)に達したため最近傍へ割当: %s distance=%.3f (threshold=%.3f)",
                    self._max_speakers,
                    best_speaker.label,
                    best_distance,
                    self._threshold,
                )
            else:
                logger.debug(
                    "既存話者に割当: %s distance=%.3f (threshold=%.3f)",
                    best_speaker.label,
                    best_distance,
                    self._threshold,
                )
            return self._bind_to_speaker(best_speaker, embedding)

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
        distance_text = f"{best_distance:.3f}" if best_speaker is not None else "n/a"
        logger.info(
            "新しい話者を検出しました: %s (meeting_id=%s, nearest_distance=%s, "
            "threshold=%.3f, known=%d, max_speakers=%s)",
            label,
            self._meeting_id,
            distance_text,
            self._threshold,
            len(candidates),
            self._max_speakers,
        )
        return new_speaker
