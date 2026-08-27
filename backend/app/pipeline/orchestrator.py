"""音声取得〜文字起こし〜話者分離〜議事録更新までを統括するパイプライン
オーケストレーター(要件定義書 第10章・第11章 AI処理全体フロー)。

文字起こし(Whisper/GPU)は本文を先に配信し、話者分離(pyannote/CPU)と
議事録更新(Qwen3)は別スレッドで進める。同一プロセスで Whisper と pyannote を
両方 cuda にすると Windows で cuDNN 競合するため、話者分離は CPU のまま重ねる。
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import numpy as np

from app.audio.capture import WasapiLoopbackCapture
from app.audio.chunker import AudioChunk, AudioChunker
from app.config import Settings
from app.db.models import Meeting, MeetingStatus, MinutesSnapshot, Participant, Utterance
from app.db.session import SessionLocal
from app.pipeline.asr import TranscribedSegment, WhisperTranscriber
from app.pipeline.diarization import (
    DiarizationEngine,
    SpeakerRegistry,
    resolve_max_speakers,
    slice_audio,
    speakers_for_segments,
)
from app.pipeline.minutes import MinutesData, MinutesGenerator

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[int, dict], Awaitable[None]]
_SENTINEL = object()


@dataclass
class _DiarizeJob:
    samples: np.ndarray
    sample_rate: int
    chunk_start_ms: int
    utterance_ids: list[int]
    queued_at: float


@dataclass
class _MinutesJob:
    new_text: str


@dataclass
class _MeetingRuntime:
    meeting_id: int
    stop_event: threading.Event
    thread: threading.Thread
    capture: WasapiLoopbackCapture | None = None
    min_speakers: int | None = None
    started_at: float = field(default_factory=time.time)
    chars_since_minutes_update: int = 0
    last_minutes_update_ts: float = field(default_factory=time.time)
    pending_transcript_buffer: list[str] = field(default_factory=list)
    buffer_lock: threading.Lock = field(default_factory=threading.Lock)
    diarize_queue: queue.Queue = field(default_factory=queue.Queue)
    minutes_queue: queue.Queue = field(default_factory=queue.Queue)
    diarize_thread: threading.Thread | None = None
    minutes_thread: threading.Thread | None = None
    workers_drained: bool = False


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

    def stop_meeting(self, meeting_id: int, timeout: float = 120.0) -> None:
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

    def _utterance_message(self, utterance: Utterance, speaker_label: str | None) -> dict:
        return {
            "type": "utterance",
            "utterance": {
                "id": utterance.id,
                "start_ms": utterance.start_ms,
                "end_ms": utterance.end_ms,
                "text": utterance.raw_text,
                "raw_text": utterance.raw_text,
                "effective_text": utterance.effective_text,
                "corrected_text": utterance.corrected_text,
                "speaker_id": utterance.speaker_id,
                "effective_speaker_id": utterance.effective_speaker_id,
                "speaker_label": speaker_label,
            },
        }

    # ------------------------------------------------------------------
    # ワーカースレッド本体
    # ------------------------------------------------------------------
    def _run_meeting_loop(self, meeting_id: int, stop_event: threading.Event) -> None:
        db = SessionLocal()
        runtime = self._runtimes[meeting_id]
        finalized = False
        try:
            self._start_worker_threads(runtime)
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

            final_chunk = chunker.flush()
            if final_chunk is not None:
                self._process_chunk(db, meeting_id, final_chunk, runtime)

            self._drain_workers(runtime)
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
            self._drain_workers(runtime)
            if not finalized:
                # 音声取得自体の失敗等で最終化に到達できなかった場合でも、会議が
                # 「進行中」のまま残り続けてUIが操作不能にならないよう終了扱いにする
                try:
                    self._finalize_meeting(db, meeting_id, runtime)
                except Exception:
                    logger.exception("会議%sの終了処理(フォールバック)にも失敗しました", meeting_id)
            db.close()

    def _start_worker_threads(self, runtime: _MeetingRuntime) -> None:
        runtime.diarize_thread = threading.Thread(
            target=self._run_diarize_loop,
            args=(runtime,),
            daemon=True,
            name=f"diarize-{runtime.meeting_id}",
        )
        runtime.minutes_thread = threading.Thread(
            target=self._run_minutes_loop,
            args=(runtime,),
            daemon=True,
            name=f"minutes-{runtime.meeting_id}",
        )
        runtime.diarize_thread.start()
        runtime.minutes_thread.start()

    def _drain_workers(self, runtime: _MeetingRuntime) -> None:
        if runtime.workers_drained:
            return
        runtime.workers_drained = True
        runtime.diarize_queue.put(_SENTINEL)
        if runtime.diarize_thread is not None:
            runtime.diarize_thread.join(timeout=120.0)
        runtime.minutes_queue.put(_SENTINEL)
        if runtime.minutes_thread is not None:
            runtime.minutes_thread.join(timeout=120.0)

    def _max_speakers_hint(self, db, meeting_id: int, runtime: _MeetingRuntime) -> int | None:
        participant_count = (
            db.query(Participant).filter(Participant.meeting_id == meeting_id).count()
        )
        return resolve_max_speakers(
            self._settings.diarization_min_speakers,
            runtime.min_speakers,
            participant_count,
        )

    def _process_chunk(
        self, db, meeting_id: int, chunk: AudioChunk, runtime: _MeetingRuntime
    ) -> None:
        asr_started = time.time()
        try:
            segments = self._transcriber.transcribe_chunk(
                chunk.samples, chunk.sample_rate, chunk.start_ms
            )
        except Exception:
            logger.exception("文字起こしに失敗しました。このチャンクをスキップします")
            return

        asr_s = time.time() - asr_started
        lag_s = time.time() - (runtime.started_at + chunk.start_ms / 1000.0)
        duration_s = (chunk.end_ms - chunk.start_ms) / 1000.0
        logger.info(
            "文字起こし完了: meeting_id=%s start_ms=%d duration_s=%.1f asr_s=%.2f "
            "lag_s=%.1f segs=%d",
            meeting_id,
            chunk.start_ms,
            duration_s,
            asr_s,
            lag_s,
            len(segments),
        )
        if not segments:
            return

        utterance_ids: list[int] = []
        for seg in segments:
            try:
                utterance = Utterance(
                    meeting_id=meeting_id,
                    speaker_id=None,
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

            utterance_ids.append(utterance.id)
            with runtime.buffer_lock:
                runtime.pending_transcript_buffer.append(seg.text)
                runtime.chars_since_minutes_update += len(seg.text)

            self._emit(meeting_id, self._utterance_message(utterance, speaker_label=None))

        if not utterance_ids:
            return

        runtime.diarize_queue.put(
            _DiarizeJob(
                samples=np.ascontiguousarray(chunk.samples.copy()),
                sample_rate=chunk.sample_rate,
                chunk_start_ms=chunk.start_ms,
                utterance_ids=utterance_ids,
                queued_at=time.time(),
            )
        )
        self._maybe_schedule_minutes(runtime)

    def _run_diarize_loop(self, runtime: _MeetingRuntime) -> None:
        db = SessionLocal()
        try:
            while True:
                job = runtime.diarize_queue.get()
                if job is _SENTINEL:
                    break
                try:
                    self._process_diarize_job(db, runtime, job)
                except Exception:
                    logger.exception(
                        "話者分離ジョブの処理に失敗しました(会議%s)", runtime.meeting_id
                    )
                    db.rollback()
        finally:
            db.close()

    def _process_diarize_job(
        self, db, runtime: _MeetingRuntime, job: _DiarizeJob
    ) -> None:
        meeting_id = runtime.meeting_id
        started = time.time()
        queue_wait_s = started - job.queued_at
        max_speakers = self._max_speakers_hint(db, meeting_id, runtime)

        try:
            turns = self._diarizer.diarize_chunk(
                job.samples,
                job.sample_rate,
                max_speakers=max_speakers,
            )
        except Exception:
            logger.exception("話者分離に失敗しました。話者未割当のまま続行します")
            return

        for turn in turns:
            turn.start_ms += job.chunk_start_ms
            turn.end_ms += job.chunk_start_ms

        utterances = (
            db.query(Utterance).filter(Utterance.id.in_(job.utterance_ids)).all()
        )
        by_id = {utterance.id: utterance for utterance in utterances}
        ordered = [by_id[uid] for uid in job.utterance_ids if uid in by_id]
        if not ordered:
            return

        registry = SpeakerRegistry(
            db,
            meeting_id,
            similarity_threshold=self._settings.speaker_similarity_threshold,
            max_speakers=max_speakers,
        )

        def embed_segment(segment: TranscribedSegment | Utterance):
            clip = slice_audio(
                job.samples,
                job.sample_rate,
                job.chunk_start_ms,
                segment.start_ms,
                segment.end_ms,
            )
            return self._diarizer.embed_clip(clip, job.sample_rate)

        try:
            segment_speakers = speakers_for_segments(registry, ordered, turns, embed_segment)
        except Exception:
            logger.exception("話者割当に失敗しました。話者未割当のまま続行します")
            return

        for utterance, speaker in zip(ordered, segment_speakers, strict=True):
            if speaker is None:
                continue
            try:
                utterance.speaker_id = speaker.id
                db.add(utterance)
                db.commit()
                db.refresh(utterance)
            except Exception:
                logger.exception("話者の保存に失敗しました。この発言をスキップします")
                db.rollback()
                continue
            speaker_label = speaker.display_label or speaker.label
            self._emit(meeting_id, self._utterance_message(utterance, speaker_label))

        logger.info(
            "話者分離完了: meeting_id=%s start_ms=%d diarize_s=%.2f queue_wait_s=%.2f "
            "utterances=%d max_speakers=%s",
            meeting_id,
            job.chunk_start_ms,
            time.time() - started,
            queue_wait_s,
            len(ordered),
            max_speakers,
        )

    def _run_minutes_loop(self, runtime: _MeetingRuntime) -> None:
        db = SessionLocal()
        try:
            while True:
                job = runtime.minutes_queue.get()
                if job is _SENTINEL:
                    break
                try:
                    current = self._load_latest_minutes(db, runtime.meeting_id)
                    updated = self._minutes_generator.update(current, job.new_text)
                    self._save_minutes_snapshot(
                        db, runtime.meeting_id, updated, is_final=False
                    )
                except Exception:
                    logger.exception(
                        "議事録の差分更新に失敗しました(会議%s)", runtime.meeting_id
                    )
                    db.rollback()
        finally:
            db.close()

    def _maybe_schedule_minutes(self, runtime: _MeetingRuntime) -> None:
        with runtime.buffer_lock:
            elapsed = time.time() - runtime.last_minutes_update_ts
            threshold_hit = (
                runtime.chars_since_minutes_update
                >= self._settings.minutes_update_char_threshold
            )
            interval_hit = elapsed >= self._settings.minutes_update_interval_seconds
            has_new_text = len(runtime.pending_transcript_buffer) > 0
            if not has_new_text or not (threshold_hit or interval_hit):
                return
            new_text = "\n".join(runtime.pending_transcript_buffer)
            runtime.pending_transcript_buffer = []
            runtime.chars_since_minutes_update = 0
            runtime.last_minutes_update_ts = time.time()
        runtime.minutes_queue.put(_MinutesJob(new_text=new_text))

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
