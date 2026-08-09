"""参加者管理API(要件定義書 第22章)。

参加者は一度も発言しない可能性があるため、音声認識に依存せず手動で登録・修正できる
ようにする。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Meeting, Participant
from app.db.session import get_db
from app.schemas import ParticipantCreate, ParticipantOut

router = APIRouter(prefix="/api/meetings/{meeting_id}/participants", tags=["participants"])


@router.get("", response_model=list[ParticipantOut])
async def list_participants(meeting_id: int, db: Session = Depends(get_db)) -> list[Participant]:
    return (
        db.query(Participant)
        .filter(Participant.meeting_id == meeting_id)
        .order_by(Participant.created_at)
        .all()
    )


@router.post("", response_model=ParticipantOut)
async def create_participant(
    meeting_id: int, payload: ParticipantCreate, db: Session = Depends(get_db)
) -> Participant:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会議が見つかりません")

    participant = Participant(meeting_id=meeting_id, name=payload.name, source="manual")
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


@router.patch("/{participant_id}", response_model=ParticipantOut)
async def rename_participant(
    meeting_id: int,
    participant_id: int,
    payload: ParticipantCreate,
    db: Session = Depends(get_db),
) -> Participant:
    participant = db.get(Participant, participant_id)
    if participant is None or participant.meeting_id != meeting_id:
        raise HTTPException(status_code=404, detail="参加者が見つかりません")
    participant.name = payload.name
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


@router.delete("/{participant_id}", status_code=204, response_model=None)
async def delete_participant(
    meeting_id: int, participant_id: int, db: Session = Depends(get_db)
) -> None:
    participant = db.get(Participant, participant_id)
    if participant is None or participant.meeting_id != meeting_id:
        raise HTTPException(status_code=404, detail="参加者が見つかりません")
    db.delete(participant)
    db.commit()
