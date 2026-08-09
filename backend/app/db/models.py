"""SQLAlchemyモデル定義。

データレイヤー方針(要件定義書 第29章)に対応する:
    Layer1 Raw Transcript      -> Utterance.raw_text (不変)
    Layer2 Corrected Transcript -> Utterance.corrected_text / corrected_speaker_id
    Layer3 Minutes              -> MinutesSnapshot

RawとCorrectedは同じUtterance行の別カラムに保持し、Rawを絶対に上書きしない。
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class MeetingStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    ENDED = "ended"


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="無題の会議")
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus), default=MeetingStatus.IN_PROGRESS
    )
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    speakers: Mapped[list["Speaker"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    utterances: Mapped[list["Utterance"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    minutes_snapshots: Mapped[list["MinutesSnapshot"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class Participant(Base):
    """会議参加者(要件定義書 第22章)。発言しない参加者にも対応するため、音声認識とは別に手動登録する。"""

    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(50), default="manual")  # manual / ocr
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="participants")
    speakers: Mapped[list["Speaker"]] = relationship(back_populates="participant")


class Speaker(Base):
    """pyannoteが生成するSpeaker ID(speaker_01等)。

    話者統合(要件定義書 第20章)では merged_into_id に統合先のSpeaker.idを設定し、
    以後はそちらを正とする。embedding_centroid はオンライン話者クラスタリング用の
    平均embeddingベクトル(JSON配列)。
    """

    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    label: Mapped[str] = mapped_column(String(50))  # speaker_01, speaker_02, ...
    display_label: Mapped[str] = mapped_column(String(50), default="")  # 話者A, 話者B, ...
    participant_id: Mapped[int | None] = mapped_column(
        ForeignKey("participants.id"), nullable=True
    )
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("speakers.id"), nullable=True
    )
    embedding_centroid: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="speakers")
    participant: Mapped[Participant | None] = relationship(back_populates="speakers")


class Utterance(Base):
    """発言単位のデータ(要件定義書 第14章・第29章)。

    raw_text / raw_speaker_id は Whisper+pyannoteの生出力であり、修正しても上書きしない。
    corrected_text / corrected_speaker_id は人間による修正結果(未修正ならNULL)。
    """

    __tablename__ = "utterances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    speaker_id: Mapped[int | None] = mapped_column(ForeignKey("speakers.id"), nullable=True)

    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)

    raw_text: Mapped[str] = mapped_column(Text)
    corrected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_speaker_id: Mapped[int | None] = mapped_column(
        ForeignKey("speakers.id"), nullable=True
    )
    is_manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="utterances")
    speaker: Mapped[Speaker | None] = relationship(foreign_keys=[speaker_id])
    corrected_speaker: Mapped[Speaker | None] = relationship(
        foreign_keys=[corrected_speaker_id]
    )

    @property
    def effective_text(self) -> str:
        return self.corrected_text if self.corrected_text is not None else self.raw_text

    @property
    def effective_speaker_id(self) -> int | None:
        return (
            self.corrected_speaker_id
            if self.corrected_speaker_id is not None
            else self.speaker_id
        )


class MinutesSnapshot(Base):
    """Qwen3が生成する構造化議事録(要件定義書 第23〜24章、第29章 Layer3)。

    会議の進行に合わせて version を重ねて保存し、is_final=True のものが
    会議終了後の最終議事録となる。
    """

    __tablename__ = "minutes_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)

    topics: Mapped[list] = mapped_column(JSON, default=list)
    decisions: Mapped[list] = mapped_column(JSON, default=list)
    todos: Mapped[list] = mapped_column(JSON, default=list)
    pending_items: Mapped[list] = mapped_column(JSON, default=list)
    confirmations: Mapped[list] = mapped_column(JSON, default=list)
    changes_from_previous: Mapped[list] = mapped_column(JSON, default=list)

    # 人間が最終確認・修正した際に手動編集フラグを立て、以後の自動更新で上書きしないようにする
    is_manually_edited: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="minutes_snapshots")
