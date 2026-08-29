"""まとめ(議事録等)の取得・確認・修正API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import MinutesSnapshot
from app.db.session import get_db
from app.pipeline.minutes import sections_from_snapshot
from app.schemas import MinutesEditRequest, MinutesOut

router = APIRouter(prefix="/api/meetings/{meeting_id}/minutes", tags=["minutes"])


def _to_out(snapshot: MinutesSnapshot) -> MinutesOut:
    return MinutesOut(
        id=snapshot.id,
        meeting_id=snapshot.meeting_id,
        version=snapshot.version,
        is_final=snapshot.is_final,
        is_manually_edited=snapshot.is_manually_edited,
        sections=sections_from_snapshot(snapshot),
        created_at=snapshot.created_at,
    )


def _latest(db: Session, meeting_id: int) -> MinutesSnapshot | None:
    return (
        db.query(MinutesSnapshot)
        .filter(MinutesSnapshot.meeting_id == meeting_id)
        .order_by(MinutesSnapshot.version.desc())
        .first()
    )


@router.get("/latest", response_model=MinutesOut)
async def get_latest_minutes(meeting_id: int, db: Session = Depends(get_db)) -> MinutesOut:
    snapshot = _latest(db, meeting_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="まとめがまだ生成されていません")
    return _to_out(snapshot)


@router.get("", response_model=list[MinutesOut])
async def list_minutes_history(
    meeting_id: int, db: Session = Depends(get_db)
) -> list[MinutesOut]:
    snapshots = (
        db.query(MinutesSnapshot)
        .filter(MinutesSnapshot.meeting_id == meeting_id)
        .order_by(MinutesSnapshot.version)
        .all()
    )
    return [_to_out(s) for s in snapshots]


@router.patch("/latest", response_model=MinutesOut)
async def edit_latest_minutes(
    meeting_id: int, payload: MinutesEditRequest, db: Session = Depends(get_db)
) -> MinutesOut:
    """会議中・会議後の人手によるまとめ修正。

    最新スナップショットを直接更新し is_manually_edited を立てる。次回の自動更新
    (差分更新)はこの修正後の内容を起点として実行される。
    """
    snapshot = _latest(db, meeting_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="まとめがまだ生成されていません")

    update_data = payload.model_dump(exclude_unset=True)
    if "sections" in update_data and update_data["sections"] is not None:
        snapshot.sections = update_data["sections"]
        # 新規は sections が正。旧カラムは空に揃える
        snapshot.topics = []
        snapshot.decisions = []
        snapshot.todos = []
        snapshot.pending_items = []
        snapshot.confirmations = []
        snapshot.changes_from_previous = []
    snapshot.is_manually_edited = True

    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return _to_out(snapshot)
