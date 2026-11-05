"""API・AI出力・DBで共通に使う型定義。"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

UNKNOWN = "不明"
NOT_SPECIFIED = "会議中に明確な指定なし"


class MeetingStatus(StrEnum):
    UPLOADED = "UPLOADED"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIBED = "TRANSCRIBED"
    ANALYZING = "ANALYZING"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class PipelineStep(StrEnum):
    """処理ステップ。error_step にはこの値を保存し、再試行時はここから再開する。"""

    TRANSCRIBE = "transcribe"
    ANALYZE = "analyze"
    GENERATE = "generate"
    DROPBOX = "dropbox"


MeetingTool = Literal["zoom", "google_meet", "teams", "other"]
InputType = Literal["audio", "video", "text"]
FileType = Literal["transcript", "docx", "pdf"]


# ---------- 議事録の種類（項目の定義は app/services/minutes_types.py） ----------

MinutesTypeKey = Literal["record", "review", "daily"]
# 議事録の中身。キーは種類ごとの項目（文字列・文字列の配列・TODO の配列）
MinutesContent = dict[str, Any]


class MeetingInfo(BaseModel):
    """AI 入力・文書生成に使う会議情報（設計書21章）。"""

    meeting_name: str
    meeting_datetime: datetime
    meeting_tool: MeetingTool = "other"
    participants: list[str] = Field(default_factory=list)


# ---------- API ----------


class MeetingCreate(BaseModel):
    meeting_name: str = Field(min_length=1, max_length=100)
    meeting_datetime: datetime
    meeting_tool: MeetingTool = "other"
    participants: list[str] = Field(default_factory=list, max_length=50)
    input_type: InputType
    minutes_type: MinutesTypeKey = "record"
    file_name: str = Field(min_length=1, max_length=255)
    file_size: int = Field(gt=0)


class Participant(BaseModel):
    id: str
    name: str
    email: str | None = None


class Meeting(BaseModel):
    id: str
    meeting_name: str
    meeting_datetime: datetime
    meeting_tool: MeetingTool
    input_type: InputType
    minutes_type: MinutesTypeKey = "record"
    source_file_name: str | None = None
    status: MeetingStatus
    error_step: PipelineStep | None = None
    error_message: str | None = None
    dropbox_folder_path: str | None = None
    created_at: datetime
    updated_at: datetime
    participants: list[Participant] = Field(default_factory=list)


class MeetingCreateResponse(BaseModel):
    meeting: Meeting
    upload_path: str
    upload_token: str


class MinutesResponse(BaseModel):
    meeting_id: str
    minutes_type: MinutesTypeKey
    data: MinutesContent
    ai_model: str | None = None
    edited_at: datetime | None = None


class MinutesUpdate(BaseModel):
    data: MinutesContent


class FileUrlResponse(BaseModel):
    url: str
    file_name: str


class DropboxStatus(BaseModel):
    connected: bool
    email: str | None = None
    configured: bool


class DropboxConnectResponse(BaseModel):
    authorize_url: str
