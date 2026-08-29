"""API入出力用のPydanticスキーマ。"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models import DEFAULT_SUMMARY_MODE, SUMMARY_MODES


class MeetingCreate(BaseModel):
    title: str = "無題の会議"
    min_speakers: int | None = None
    summary_mode: str = DEFAULT_SUMMARY_MODE

    @field_validator("summary_mode")
    @classmethod
    def _validate_summary_mode(cls, value: str) -> str:
        mode = (value or DEFAULT_SUMMARY_MODE).strip().lower()
        if mode not in SUMMARY_MODES:
            return DEFAULT_SUMMARY_MODE
        return mode


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    summary_mode: str = DEFAULT_SUMMARY_MODE
    started_at: dt.datetime
    ended_at: dt.datetime | None


class ParticipantCreate(BaseModel):
    name: str


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    name: str
    source: str


class SpeakerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    label: str
    display_label: str
    participant_id: int | None
    merged_into_id: int | None


class SpeakerAssignRequest(BaseModel):
    participant_name: str


class SpeakerMergeRequest(BaseModel):
    into_speaker_id: int


class UtteranceOut(BaseModel):
    id: int
    meeting_id: int
    speaker_id: int | None
    speaker_label: str | None
    start_ms: int
    end_ms: int
    raw_text: str
    corrected_text: str | None
    corrected_speaker_id: int | None
    is_manually_corrected: bool
    effective_text: str
    effective_speaker_id: int | None


class UtteranceCorrectionRequest(BaseModel):
    corrected_text: str | None = None
    corrected_speaker_id: int | None = None


class MinutesOut(BaseModel):
    id: int
    meeting_id: int
    version: int
    is_final: bool
    is_manually_edited: bool
    sections: list[dict]
    created_at: dt.datetime


class MinutesEditRequest(BaseModel):
    sections: list[dict] | None = None
