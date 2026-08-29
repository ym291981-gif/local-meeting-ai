"""会議の開始・終了・一覧取得API(要件定義書 第32章 MVP要件)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_orchestrator
from app.db.models import DEFAULT_SUMMARY_MODE, Meeting, MeetingStatus
from app.db.session import get_db
from app.pipeline.minutes import normalize_summary_mode
from app.pipeline.orchestrator import PipelineOrchestrator
from app.schemas import MeetingCreate, MeetingOut

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.post("", response_model=MeetingOut)
async def create_and_start_meeting(
    payload: MeetingCreate,
    db: Session = Depends(get_db),
    orchestrator: PipelineOrchestrator = Depends(get_orchestrator),
) -> Meeting:
    """新しい会議を作成し、即座にPC内部音声の取得〜文字起こしパイプラインを開始する。"""
    summary_mode = normalize_summary_mode(payload.summary_mode)
    meeting = Meeting(
        title=payload.title,
        status=MeetingStatus.IN_PROGRESS,
        summary_mode=summary_mode or DEFAULT_SUMMARY_MODE,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    orchestrator.start_meeting(
        meeting.id,
        min_speakers=payload.min_speakers,
        summary_mode=meeting.summary_mode,
    )
    return meeting


@router.get("", response_model=list[MeetingOut])
async def list_meetings(db: Session = Depends(get_db)) -> list[Meeting]:
    return db.query(Meeting).order_by(Meeting.started_at.desc()).all()


@router.get("/{meeting_id}", response_model=MeetingOut)
async def get_meeting(meeting_id: int, db: Session = Depends(get_db)) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会議が見つかりません")
    return meeting


@router.post("/{meeting_id}/stop", response_model=MeetingOut)
async def stop_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    orchestrator: PipelineOrchestrator = Depends(get_orchestrator),
) -> Meeting:
    """会議を終了し、最終議事録の生成とLayer別データの独立保存を行う(第27・28章)。"""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会議が見つかりません")

    # 停止処理(最終議事録生成含む)は数十秒かかる可能性があるためスレッドプールで実行し、
    # イベントループをブロックしないようにする
    await run_in_threadpool(orchestrator.stop_meeting, meeting_id)

    db.refresh(meeting)
    return meeting
