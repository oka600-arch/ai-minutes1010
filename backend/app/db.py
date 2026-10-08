"""Supabase（PostgreSQL / Storage）へのアクセス。FastAPI は service role キーで接続し、
ユーザーごとのアクセス制御は各関数の user_id 条件で行う（ブラウザ側は RLS で保護）。"""

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from supabase import Client, create_client

from app.config import get_settings
from app.schemas import FileType, MeetingCreate, MeetingStatus, MinutesData, PipelineStep

UPLOAD_BUCKET = "uploads"
OUTPUT_BUCKET = "outputs"


@lru_cache
def get_client() -> Client:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が設定されていません。")
    return create_client(s.supabase_url, s.supabase_service_role_key)


class Repository:
    def __init__(self, client: Client | None = None) -> None:
        self.c = client or get_client()

    # ---------- 認証 ----------

    def user_id_from_token(self, access_token: str) -> str | None:
        try:
            res = self.c.auth.get_user(access_token)
        except Exception:
            return None
        return res.user.id if res and res.user else None

    # ---------- meetings ----------

    def create_meeting(self, user_id: str, body: MeetingCreate, source_path: str, meeting_id: str) -> dict[str, Any]:
        row = {
            "id": meeting_id,
            "user_id": user_id,
            "meeting_name": body.meeting_name.strip(),
            "meeting_datetime": body.meeting_datetime.isoformat(),
            "meeting_tool": body.meeting_tool,
            "input_type": body.input_type,
            "source_file_name": body.file_name,
            "source_file_path": source_path,
            "status": MeetingStatus.UPLOADED,
        }
        meeting = self.c.table("meetings").insert(row).execute().data[0]
        names = [n.strip() for n in body.participants if n.strip()]
        if names:
            self.c.table("participants").insert([{"meeting_id": meeting_id, "name": n} for n in names]).execute()
        return meeting

    def get_meeting(self, meeting_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        q = self.c.table("meetings").select("*, participants(id, name, email)").eq("id", meeting_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        rows = q.limit(1).execute().data
        return rows[0] if rows else None

    def list_meetings(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return (
            self.c.table("meetings")
            .select("*, participants(id, name, email)")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    def update_meeting(self, meeting_id: str, **fields: Any) -> None:
        self.c.table("meetings").update(fields).eq("id", meeting_id).execute()

    def set_status(self, meeting_id: str, status: MeetingStatus) -> None:
        self.update_meeting(meeting_id, status=status, error_step=None, error_message=None)

    def set_error(self, meeting_id: str, step: PipelineStep, message: str) -> None:
        self.update_meeting(meeting_id, status=MeetingStatus.ERROR, error_step=step, error_message=message)

    def claim_for_processing(self, meeting_id: str, allowed: list[MeetingStatus], stale_before: datetime) -> bool:
        """二重実行を防ぐ。許可されたステータス、または一定時間更新のない処理中の会議だけを取得する。"""
        in_progress = [MeetingStatus.TRANSCRIBING, MeetingStatus.ANALYZING, MeetingStatus.GENERATING, MeetingStatus.UPLOADING]
        meeting = self.get_meeting(meeting_id)
        if meeting is None:
            return False
        status = MeetingStatus(meeting["status"])
        if status in allowed:
            pass
        elif status in in_progress and datetime.fromisoformat(meeting["updated_at"]) < stale_before:
            pass  # サーバー再起動などで止まった処理は再開を許可する
        else:
            return False
        # updated_at を条件にした楽観ロック（同時に2回押されても片方だけが成功する）
        res = (
            self.c.table("meetings")
            .update({"error_message": None})
            .eq("id", meeting_id)
            .eq("updated_at", meeting["updated_at"])
            .execute()
        )
        return bool(res.data)

    # ---------- transcripts / minutes / files ----------

    def save_transcript(self, meeting_id: str, source_format: str, file_path: str | None, text: str) -> None:
        self.c.table("transcripts").upsert(
            {"meeting_id": meeting_id, "source_format": source_format, "file_path": file_path, "transcript_text": text},
            on_conflict="meeting_id",
        ).execute()

    def get_transcript(self, meeting_id: str) -> str | None:
        rows = self.c.table("transcripts").select("transcript_text").eq("meeting_id", meeting_id).limit(1).execute().data
        return rows[0]["transcript_text"] if rows else None

    def save_minutes(self, meeting_id: str, minutes: MinutesData, model: str) -> None:
        self.c.table("meeting_minutes").upsert(
            {"meeting_id": meeting_id, "ai_model": model, **minutes.model_dump()}, on_conflict="meeting_id"
        ).execute()

    def get_minutes(self, meeting_id: str) -> dict[str, Any] | None:
        rows = self.c.table("meeting_minutes").select("*").eq("meeting_id", meeting_id).limit(1).execute().data
        return rows[0] if rows else None

    def save_file(self, meeting_id: str, file_type: FileType, file_name: str, file_path: str) -> None:
        self.c.table("files").upsert(
            {"meeting_id": meeting_id, "file_type": file_type, "file_name": file_name, "file_path": file_path, "dropbox_path": None},
            on_conflict="meeting_id,file_type",
        ).execute()

    def list_files(self, meeting_id: str) -> list[dict[str, Any]]:
        return self.c.table("files").select("*").eq("meeting_id", meeting_id).execute().data

    def set_file_dropbox_path(self, meeting_id: str, file_type: FileType, dropbox_path: str) -> None:
        self.c.table("files").update({"dropbox_path": dropbox_path}).eq("meeting_id", meeting_id).eq("file_type", file_type).execute()

    # ---------- Dropbox ----------

    def get_dropbox_connection(self, user_id: str) -> dict[str, Any] | None:
        rows = self.c.table("dropbox_connections").select("*").eq("user_id", user_id).limit(1).execute().data
        return rows[0] if rows else None

    def save_dropbox_connection(self, user_id: str, account_id: str, email: str | None, encrypted_token: str) -> None:
        self.c.table("dropbox_connections").upsert(
            {"user_id": user_id, "dropbox_account_id": account_id, "dropbox_email": email, "refresh_token_encrypted": encrypted_token},
            on_conflict="user_id",
        ).execute()

    def delete_dropbox_connection(self, user_id: str) -> None:
        self.c.table("dropbox_connections").delete().eq("user_id", user_id).execute()

    def save_oauth_state(self, state: str, user_id: str, code_verifier: str) -> None:
        self.c.table("dropbox_oauth_states").insert({"state": state, "user_id": user_id, "code_verifier": code_verifier}).execute()

    def pop_oauth_state(self, state: str, max_age: timedelta = timedelta(minutes=10)) -> dict[str, Any] | None:
        rows = self.c.table("dropbox_oauth_states").select("*").eq("state", state).limit(1).execute().data
        if not rows:
            return None
        self.c.table("dropbox_oauth_states").delete().eq("state", state).execute()
        created = datetime.fromisoformat(rows[0]["created_at"])
        if datetime.now(timezone.utc) - created > max_age:
            return None
        return rows[0]

    # ---------- Storage ----------

    def create_upload_url(self, path: str) -> str:
        res = self.c.storage.from_(UPLOAD_BUCKET).create_signed_upload_url(path)
        return res["token"]

    def download(self, bucket: str, path: str) -> bytes:
        return self.c.storage.from_(bucket).download(path)

    def upload_output(self, path: str, content: bytes, content_type: str) -> None:
        self.c.storage.from_(OUTPUT_BUCKET).upload(path, content, {"content-type": content_type, "upsert": "true"})

    def remove(self, bucket: str, path: str) -> None:
        self.c.storage.from_(bucket).remove([path])

    def signed_download_url(self, path: str, download_name: str, expires_in: int = 300) -> str:
        # 日本語のファイル名はクエリ文字列に入るので URL エンコードしておく
        res = self.c.storage.from_(OUTPUT_BUCKET).create_signed_url(path, expires_in, {"download": quote(download_name)})
        return res["signedURL"]
