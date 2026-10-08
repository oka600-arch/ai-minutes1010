import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.schemas import MeetingStatus, MinutesData

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample-data"


@pytest.fixture
def sample_minutes() -> MinutesData:
    return MinutesData.model_validate(json.loads((SAMPLE_DIR / "expected_minutes.json").read_text(encoding="utf-8")))


class FakeRepo:
    """Repository のメモリ上の代替（Supabase なしでテストするため）。"""

    def __init__(self) -> None:
        self.meetings: dict[str, dict[str, Any]] = {}
        self.transcripts: dict[str, str] = {}
        self.minutes: dict[str, dict[str, Any]] = {}
        self.files: dict[tuple[str, str], dict[str, Any]] = {}
        self.storage: dict[tuple[str, str], bytes] = {}
        self.dropbox: dict[str, dict[str, Any]] = {}
        self.status_history: list[str] = []
        self.tokens = {"token-a": "user-a", "token-b": "user-b"}

    def user_id_from_token(self, token: str) -> str | None:
        return self.tokens.get(token)

    def add_meeting(self, meeting_id: str, user_id: str = "user-a", **fields: Any) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": meeting_id, "user_id": user_id, "meeting_name": "営業部 定例会議",
            "meeting_datetime": "2026-10-08T10:00:00+09:00", "meeting_tool": "zoom", "input_type": "text",
            "source_file_name": "m.txt", "source_file_path": f"{user_id}/{meeting_id}/source.txt",
            "status": "UPLOADED", "error_step": None, "error_message": None, "dropbox_folder_path": None,
            "created_at": now, "updated_at": now,
            "participants": [{"id": "p1", "name": "山田", "email": None}, {"id": "p2", "name": "佐藤", "email": None}],
        }
        row.update(fields)
        self.meetings[meeting_id] = row
        return row

    def create_meeting(self, user_id, body, source_path, meeting_id):
        return self.add_meeting(
            meeting_id, user_id, meeting_name=body.meeting_name, input_type=body.input_type,
            source_file_name=body.file_name, source_file_path=source_path,
            meeting_datetime=body.meeting_datetime.isoformat(),
            participants=[{"id": str(i), "name": n, "email": None} for i, n in enumerate(body.participants)],
        )

    def get_meeting(self, meeting_id, user_id=None):
        m = self.meetings.get(meeting_id)
        if m is None or (user_id is not None and m["user_id"] != user_id):
            return None
        return deepcopy(m)

    def list_meetings(self, user_id, limit=50):
        return [deepcopy(m) for m in self.meetings.values() if m["user_id"] == user_id]

    def update_meeting(self, meeting_id, **fields):
        self.meetings[meeting_id].update(fields)
        self.meetings[meeting_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def set_status(self, meeting_id, status):
        self.status_history.append(str(status))
        self.update_meeting(meeting_id, status=str(status), error_step=None, error_message=None)

    def set_error(self, meeting_id, step, message):
        self.status_history.append("ERROR")
        self.update_meeting(meeting_id, status="ERROR", error_step=str(step), error_message=message)

    def claim_for_processing(self, meeting_id, allowed, stale_before):
        return MeetingStatus(self.meetings[meeting_id]["status"]) in allowed

    def save_transcript(self, meeting_id, source_format, file_path, text):
        self.transcripts[meeting_id] = text

    def get_transcript(self, meeting_id):
        return self.transcripts.get(meeting_id)

    def save_minutes(self, meeting_id, minutes, model):
        self.minutes[meeting_id] = {"meeting_id": meeting_id, "ai_model": model, **minutes.model_dump()}

    def get_minutes(self, meeting_id):
        return self.minutes.get(meeting_id)

    def save_file(self, meeting_id, file_type, file_name, file_path):
        self.files[(meeting_id, file_type)] = {"file_type": file_type, "file_name": file_name, "file_path": file_path, "dropbox_path": None}

    def list_files(self, meeting_id):
        return [f for (mid, _), f in self.files.items() if mid == meeting_id]

    def set_file_dropbox_path(self, meeting_id, file_type, dropbox_path):
        self.files[(meeting_id, file_type)]["dropbox_path"] = dropbox_path

    def get_dropbox_connection(self, user_id):
        return self.dropbox.get(user_id)

    def delete_dropbox_connection(self, user_id):
        self.dropbox.pop(user_id, None)

    def create_upload_url(self, path):
        return "upload-token"

    def download(self, bucket, path):
        return self.storage[(bucket, path)]

    def upload_output(self, path, content, content_type):
        self.storage[("outputs", path)] = content

    def remove(self, bucket, path):
        self.storage.pop((bucket, path), None)

    def signed_download_url(self, path, download_name, expires_in=300):
        return f"https://example.test/{path}?download={download_name}"


class FakeOpenAI:
    """chat.completions.create / audio.transcriptions.create だけを持つ代替。"""

    def __init__(self, content: str = "", finish_reason: str = "stop", transcript: str = "山田：テストです。") -> None:
        self.calls: list[dict[str, Any]] = []
        self.content = content
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                msg = SimpleNamespace(content=outer.content, refusal=None)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)])

        class _Transcriptions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return transcript

        self.chat = SimpleNamespace(completions=_Completions())
        self.audio = SimpleNamespace(transcriptions=_Transcriptions())


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="test-key", supabase_url="", supabase_service_role_key="")
