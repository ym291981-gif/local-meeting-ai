"""API入出力用のPydanticスキーマ。"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class MeetingCreate(BaseModel):
    title: str = "無題の会議"
    min_speakers: int | None = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
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


class MinutesTopicOut(BaseModel):
    title: str


class MinutesDecisionOut(BaseModel):
    text: str


class MinutesTodoOut(BaseModel):
    task: str
    owner: str | None = None
    deadline: str | None = None


class MinutesOut(BaseModel):
    id: int
    meeting_id: int
    version: int
    is_final: bool
    is_manually_edited: bool
    topics: list[dict]
    decisions: list[dict]
    todos: list[dict]
    pending_items: list[dict]
    confirmations: list[dict]
    changes_from_previous: list[dict]
    created_at: dt.datetime


class MinutesEditRequest(BaseModel):
    topics: list[dict] | None = None
    decisions: list[dict] | None = None
    todos: list[dict] | None = None
    pending_items: list[dict] | None = None
    confirmations: list[dict] | None = None
    changes_from_previous: list[dict] | None = None
