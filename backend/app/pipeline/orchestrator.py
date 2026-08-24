"""音声取得〜文字起こし〜話者分離〜議事録更新までを統括するパイプライン
オーケストレーター(要件定義書 第10章・第11章 AI処理全体フロー)。

Whisper・pyannote・Qwen3を「常時最大負荷で同時実行」するのではなく、チャンク
単位で順番に処理する(第11章)。音声取得はコールバックスレッド、パイプライン
処理は会議ごとの専用ワーカースレッドで行い、GPUを使うモデル呼び出しは
このワーカースレッド内で直列に実行される。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.audio.capture import WasapiLoopbackCapture
from app.audio.chunker import AudioChunk, AudioChunker
from app.config import Settings
from app.db.models import Meeting, MeetingStatus, MinutesSnapshot, Participant, Utterance
from app.db.session import SessionLocal
from app.pipeline.asr import TranscribedSegment, WhisperTranscriber
from app.pipeline.diarization import (
    DiarizationEngine,
    SpeakerRegistry,
    resolve_min_speakers,
    slice_audio,
    speakers_for_segments,
)
from app.pipeline.minutes import MinutesData, MinutesGenerator

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[int, dict], Awaitable[None]]


@dataclass
class _MeetingRuntime:
    meeting_id: int
    stop_event: threading.Event
    thread: threading.Thread
    capture: WasapiLoopbackCapture | None = None
    min_speakers: int | None = None
    chars_since_minutes_update: int = 0
    last_minutes_update_ts: float = field(default_factory=time.time)
    pending_transcript_buffer: list[str] = field(default_factory=list)


class PipelineOrchestrator:
    """会議ごとにAudio Capture〜議事録更新のパイプラインを起動・停止する。"""

    def __init__(
        self,
        settings: Settings,
        transcriber: WhisperTranscriber,
        diarizer: DiarizationEngine,
        minutes_generator: MinutesGenerator,
        broadcast: BroadcastFn,
    ) -> None:
        self._settings = settings
        self._transcriber = transcriber
        self._diarizer = diarizer
        self._minutes_generator = minutes_generator
        self._broadcast = broadcast
        self._runtimes: dict[int, _MeetingRuntime] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """FastAPI起動時のイベントループを登録する(ワーカースレッドからWS配信するため)。"""
        self._loop = loop

    def is_running(self, meeting_id: int) -> bool:
        return meeting_id in self._runtimes

    def start_meeting(self, meeting_id: int, min_speakers: int | None = None) -> None:
        if meeting_id in self._runtimes:
            logger.warning("会議%sは既に開始されています", meeting_id)
            return
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_meeting_loop, args=(meeting_id, stop_event), daemon=True
        )
        runtime = _MeetingRuntime(
            meeting_id=meeting_id,
            stop_event=stop_event,
            thread=thread,
            min_speakers=min_speakers,
        )
        self._runtimes[meeting_id] = runtime
        thread.start()

    def stop_meeting(self, meeting_id: int, timeout: float = 60.0) -> None:
        runtime = self._runtimes.get(meeting_id)
        if runtime is None:
            logger.warning("会議%sは開始されていません", meeting_id)
            return
        runtime.stop_event.set()
        runtime.thread.join(timeout=timeout)
        self._runtimes.pop(meeting_id, None)

    def _emit(self, meeting_id: int, message: dict) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(meeting_id, message), self._loop)

    # ------------------------------------------------------------------
    # ワーカースレッド本体
    # ------------------------------------------------------------------
    def _run_meeting_loop(self, meeting_id: int, stop_event: threading.Event) -> None:
        db = SessionLocal()
        runtime = self._runtimes[meeting_id]
        finalized = False
        try:
            capture = WasapiLoopbackCapture()
            runtime.capture = capture
            capture.start()
            chunker = AudioChunker(
                source_sample_rate=capture.sample_rate,
                chunk_seconds=self._settings.audio_chunk_seconds,
                target_sample_rate=self._settings.audio_target_sample_rate,
            )

            for frames in capture.iter_frames():
                if stop_event.is_set():
                    break
                for chunk in chunker.feed(frames):
                    self._process_chunk(db, meeting_id, chunk, runtime)
                self._maybe_update_minutes(db, meeting_id, runtime, force=False)

            final_chunk = chunker.flush()
            if final_chunk is not None:
                self._process_chunk(db, meeting_id, final_chunk, runtime)

            self._finalize_meeting(db, meeting_id, runtime)
            finalized = True
        except Exception:
            logger.exception("会議%sのパイプライン処理で回復不能なエラーが発生しました", meeting_id)
        finally:
            if runtime.capture is not None:
                try:
                    runtime.capture.stop()
                except Exception:
                    logger.exception("音声キャプチャの停止に失敗しました(会議%s)", meeting_id)
            if not finalized:
                # 音声取得自体の失敗等で最終化に到達できなかった場合でも、会議が
                # 「進行中」のまま残り続けてUIが操作不能にならないよう終了扱いにする
                try:
                    self._finalize_meeting(db, meeting_id, runtime)
                except Exception:
                    logger.exception("会議%sの終了処理(フォールバック)にも失敗しました", meeting_id)
            db.close()

    def _min_speakers_hint(self, db, meeting_id: int, runtime: _MeetingRuntime) -> int | None:
        participant_count = (
            db.query(Participant).filter(Participant.meeting_id == meeting_id).count()
        )
        return resolve_min_speakers(
            self._settings.diarization_min_speakers,
            runtime.min_speakers,
            participant_count,
        )

    def _process_chunk(
        self, db, meeting_id: int, chunk: AudioChunk, runtime: _MeetingRuntime
    ) -> None:
        try:
            segments = self._transcriber.transcribe_chunk(
                chunk.samples, chunk.sample_rate, chunk.start_ms
            )
        except Exception:
            logger.exception("文字起こしに失敗しました。このチャンクをスキップします")
            return
        if not segments:
            return

        try:
            turns = self._diarizer.diarize_chunk(
                chunk.samples,
                chunk.sample_rate,
                min_speakers=self._min_speakers_hint(db, meeting_id, runtime),
            )
        except Exception:
            logger.exception("話者分離に失敗しました。話者未割当のまま続行します")
            turns = []
        for turn in turns:
            turn.start_ms += chunk.start_ms
            turn.end_ms += chunk.start_ms

        registry = SpeakerRegistry(
            db, meeting_id, similarity_threshold=self._settings.speaker_similarity_threshold
        )

        def embed_segment(segment: TranscribedSegment):
            clip = slice_audio(
                chunk.samples,
                chunk.sample_rate,
                chunk.start_ms,
                segment.start_ms,
                segment.end_ms,
            )
            return self._diarizer.embed_clip(clip, chunk.sample_rate)

        try:
            segment_speakers = speakers_for_segments(registry, segments, turns, embed_segment)
        except Exception:
            logger.exception("話者割当に失敗しました。話者未割当のまま続行します")
            segment_speakers = [None] * len(segments)

        for seg, speaker in zip(segments, segment_speakers, strict=True):
            try:
                speaker_db_id = speaker.id if speaker is not None else None
                speaker_label = None
                if speaker is not None:
                    speaker_label = speaker.display_label or speaker.label

                utterance = Utterance(
                    meeting_id=meeting_id,
                    speaker_id=speaker_db_id,
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                    raw_text=seg.text,
                )
                db.add(utterance)
                db.commit()
                db.refresh(utterance)
            except Exception:
                logger.exception("発言の保存に失敗しました。この発言をスキップします")
                db.rollback()
                continue

            runtime.pending_transcript_buffer.append(seg.text)
            runtime.chars_since_minutes_update += len(seg.text)

            self._emit(
                meeting_id,
                {
                    "type": "utterance",
                    "utterance": {
                        "id": utterance.id,
                        "start_ms": utterance.start_ms,
                        "end_ms": utterance.end_ms,
                        "text": utterance.raw_text,
                        "speaker_id": utterance.speaker_id,
                        "speaker_label": speaker_label,
                    },
                },
            )

    # ------------------------------------------------------------------
    # 議事録の差分更新(要件定義書 第26章)
    # ------------------------------------------------------------------
    def _maybe_update_minutes(
        self, db, meeting_id: int, runtime: _MeetingRuntime, force: bool
    ) -> None:
        elapsed = time.time() - runtime.last_minutes_update_ts
        threshold_hit = (
            runtime.chars_since_minutes_update >= self._settings.minutes_update_char_threshold
        )
        interval_hit = elapsed >= self._settings.minutes_update_interval_seconds
        has_new_text = len(runtime.pending_transcript_buffer) > 0

        if not has_new_text:
            return
        if not (force or threshold_hit or interval_hit):
            return

        # DB上の最新スナップショットを起点にする(会議中にUIから人手修正された
        # 場合でも、その修正を基点として差分更新できるようにするため)
        current = self._load_latest_minutes(db, meeting_id)
        new_text = "\n".join(runtime.pending_transcript_buffer)
        updated = self._minutes_generator.update(current, new_text)

        self._save_minutes_snapshot(db, meeting_id, updated, is_final=False)

        runtime.pending_transcript_buffer = []
        runtime.chars_since_minutes_update = 0
        runtime.last_minutes_update_ts = time.time()

    def _load_latest_minutes(self, db, meeting_id: int) -> MinutesData:
        snapshot = (
            db.query(MinutesSnapshot)
            .filter(MinutesSnapshot.meeting_id == meeting_id)
            .order_by(MinutesSnapshot.version.desc())
            .first()
        )
        if snapshot is None:
            return MinutesData.empty()
        return MinutesData(
            topics=snapshot.topics,
            decisions=snapshot.decisions,
            todos=snapshot.todos,
            pending_items=snapshot.pending_items,
            confirmations=snapshot.confirmations,
            changes_from_previous=snapshot.changes_from_previous,
        )

    def _save_minutes_snapshot(
        self, db, meeting_id: int, minutes: MinutesData, is_final: bool
    ) -> MinutesSnapshot:
        last_version = (
            db.query(MinutesSnapshot)
            .filter(MinutesSnapshot.meeting_id == meeting_id)
            .order_by(MinutesSnapshot.version.desc())
            .first()
        )
        next_version = (last_version.version + 1) if last_version else 1

        snapshot = MinutesSnapshot(
            meeting_id=meeting_id,
            version=next_version,
            is_final=is_final,
            **minutes.to_dict(),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        self._emit(
            meeting_id,
            {
                "type": "minutes",
                "minutes": {
                    "id": snapshot.id,
                    "version": snapshot.version,
                    "is_final": snapshot.is_final,
                    **minutes.to_dict(),
                },
            },
        )
        return snapshot

    # ------------------------------------------------------------------
    # 会議終了処理(要件定義書 第27章・第28章)
    # ------------------------------------------------------------------
    def _finalize_meeting(self, db, meeting_id: int, runtime: _MeetingRuntime) -> None:
        # 会議中に修正された発言があれば反映した「修正済み全文」で最終議事録を生成する
        utterances = (
            db.query(Utterance)
            .filter(Utterance.meeting_id == meeting_id)
            .order_by(Utterance.start_ms)
            .all()
        )
        full_text = "\n".join(u.effective_text for u in utterances)

        current = self._load_latest_minutes(db, meeting_id)
        final_minutes = self._minutes_generator.generate_final(current, full_text)
        self._save_minutes_snapshot(db, meeting_id, final_minutes, is_final=True)

        meeting = db.get(Meeting, meeting_id)
        if meeting is not None:
            meeting.status = MeetingStatus.ENDED
            meeting.ended_at = _utcnow()
            db.add(meeting)
            db.commit()

        self._emit(meeting_id, {"type": "meeting_ended", "meeting_id": meeting_id})


def _utcnow():
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc)
