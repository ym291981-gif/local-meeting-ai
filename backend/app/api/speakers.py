"""話者管理API(要件定義書 第18〜21章)。

3種類の話者修正のうち、
    1. 話者名の一括割当  -> POST /{speaker_id}/assign
    2. 話者グループ統合  -> POST /{speaker_id}/merge
はここで提供する。3. 個別発言の話者変更は `app.api.transcript` の
`PATCH /utterances/{utterance_id}` (corrected_speaker_id) で提供する。
"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Participant, Speaker
from app.db.session import get_db
from app.schemas import SpeakerAssignRequest, SpeakerMergeRequest, SpeakerOut

router = APIRouter(prefix="/api/meetings/{meeting_id}/speakers", tags=["speakers"])


@router.get("", response_model=list[SpeakerOut])
async def list_speakers(meeting_id: int, db: Session = Depends(get_db)) -> list[Speaker]:
    return db.query(Speaker).filter(Speaker.meeting_id == meeting_id).order_by(Speaker.id).all()


@router.post("/{speaker_id}/assign", response_model=SpeakerOut)
async def assign_speaker_name(
    meeting_id: int,
    speaker_id: int,
    payload: SpeakerAssignRequest,
    db: Session = Depends(get_db),
) -> Speaker:
    """話者(speaker_01等)へ参加者名を割り当てる(第18・19章)。

    このSpeaker IDを参照する全発言(過去分・今後発生分の両方)へ一括反映される。
    Utterance側は speaker_id で参照しているだけなので、Speakerの表示名を
    更新すれば追加のバッチ更新は不要。
    """
    speaker = db.get(Speaker, speaker_id)
    if speaker is None or speaker.meeting_id != meeting_id:
        raise HTTPException(status_code=404, detail="話者が見つかりません")

    participant = (
        db.query(Participant)
        .filter(Participant.meeting_id == meeting_id, Participant.name == payload.participant_name)
        .first()
    )
    if participant is None:
        participant = Participant(
            meeting_id=meeting_id, name=payload.participant_name, source="manual"
        )
        db.add(participant)
        db.commit()
        db.refresh(participant)

    speaker.participant_id = participant.id
    speaker.display_label = participant.name
    db.add(speaker)
    db.commit()
    db.refresh(speaker)
    return speaker


@router.post("/{speaker_id}/merge", response_model=SpeakerOut)
async def merge_speaker(
    meeting_id: int,
    speaker_id: int,
    payload: SpeakerMergeRequest,
    db: Session = Depends(get_db),
) -> Speaker:
    """話者統合(第20章)。speaker_idをinto_speaker_idへ統合する。

    統合後は過去の発言を含めて同一人物として扱うため、embeddingの中心も
    加重平均でマージし、以後のオンライン話者クラスタリングにも反映する。
    """
    if speaker_id == payload.into_speaker_id:
        raise HTTPException(status_code=400, detail="同一の話者へ統合することはできません")

    source = db.get(Speaker, speaker_id)
    target = db.get(Speaker, payload.into_speaker_id)
    if source is None or source.meeting_id != meeting_id:
        raise HTTPException(status_code=404, detail="統合元の話者が見つかりません")
    if target is None or target.meeting_id != meeting_id:
        raise HTTPException(status_code=404, detail="統合先の話者が見つかりません")

    if source.embedding_centroid is not None and target.embedding_centroid is not None:
        s_centroid = np.asarray(source.embedding_centroid, dtype=np.float32)
        t_centroid = np.asarray(target.embedding_centroid, dtype=np.float32)
        n_s, n_t = source.embedding_count, target.embedding_count
        total = n_s + n_t
        if total > 0:
            merged = (s_centroid * n_s + t_centroid * n_t) / total
            target.embedding_centroid = merged.tolist()
            target.embedding_count = total

    source.merged_into_id = target.id
    db.add(source)
    db.add(target)
    db.commit()
    db.refresh(target)
    return target
