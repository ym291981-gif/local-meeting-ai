"""文字起こし(全文記録)取得・個別修正API(要件定義書 第14章・第21章)。

raw_text(Layer1)は不変とし、corrected_text(Layer2)のみを更新することで
一次情報を保護する。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Speaker, Utterance
from app.db.session import get_db
from app.schemas import UtteranceCorrectionRequest, UtteranceOut

router = APIRouter(prefix="/api/meetings/{meeting_id}", tags=["transcript"])


def _resolve_speaker(db: Session, speaker_id: int | None) -> Speaker | None:
    """話者統合(merged_into_id)をたどり、実際に表示すべきSpeakerを返す。"""
    if speaker_id is None:
        return None
    speaker = db.get(Speaker, speaker_id)
    visited = set()
    while speaker is not None and speaker.merged_into_id is not None:
        if speaker.id in visited:
            break
        visited.add(speaker.id)
        speaker = db.get(Speaker, speaker.merged_into_id)
    return speaker


def _to_out(db: Session, u: Utterance) -> UtteranceOut:
    speaker = _resolve_speaker(db, u.effective_speaker_id)
    return UtteranceOut(
        id=u.id,
        meeting_id=u.meeting_id,
        speaker_id=u.speaker_id,
        speaker_label=(speaker.display_label or speaker.label) if speaker else None,
        start_ms=u.start_ms,
        end_ms=u.end_ms,
        raw_text=u.raw_text,
        corrected_text=u.corrected_text,
        corrected_speaker_id=u.corrected_speaker_id,
        is_manually_corrected=u.is_manually_corrected,
        effective_text=u.effective_text,
        effective_speaker_id=u.effective_speaker_id,
    )


@router.get("/transcript", response_model=list[UtteranceOut])
async def get_transcript(meeting_id: int, db: Session = Depends(get_db)) -> list[UtteranceOut]:
    utterances = (
        db.query(Utterance)
        .filter(Utterance.meeting_id == meeting_id)
        .order_by(Utterance.start_ms)
        .all()
    )
    return [_to_out(db, u) for u in utterances]


@router.patch("/utterances/{utterance_id}", response_model=UtteranceOut)
async def correct_utterance(
    meeting_id: int,
    utterance_id: int,
    payload: UtteranceCorrectionRequest,
    db: Session = Depends(get_db),
) -> UtteranceOut:
    """個別発言の文言修正(第21章「この発言だけ話者を変更」の文言側)。"""
    utterance = db.get(Utterance, utterance_id)
    if utterance is None or utterance.meeting_id != meeting_id:
        raise HTTPException(status_code=404, detail="発言が見つかりません")

    if payload.corrected_text is not None:
        utterance.corrected_text = payload.corrected_text
    if payload.corrected_speaker_id is not None:
        utterance.corrected_speaker_id = payload.corrected_speaker_id
    utterance.is_manually_corrected = True

    db.add(utterance)
    db.commit()
    db.refresh(utterance)
    return _to_out(db, utterance)
