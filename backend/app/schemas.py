"""API・AI出力・DBで共通に使う型定義。"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

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


# ---------- AI 出力（設計書22章） ----------


class DiscussionItem(BaseModel):
    topic: str
    content: str


class TodoItem(BaseModel):
    task: str
    assignee: str
    deadline: str


class MinutesData(BaseModel):
    summary: str
    discussion: list[DiscussionItem] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    todos: list[TodoItem] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


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


class MinutesResponse(MinutesData):
    meeting_id: str
    ai_model: str | None = None


class FileUrlResponse(BaseModel):
    url: str
    file_name: str


class DropboxStatus(BaseModel):
    connected: bool
    email: str | None = None
    configured: bool


class DropboxConnectResponse(BaseModel):
    authorize_url: str
