import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.config import Settings, get_settings
from app.db import Repository
from app.deps import current_user_id, get_pipeline_deps, get_repo
from app.schemas import (
    FileType,
    FileUrlResponse,
    Meeting,
    MeetingCreate,
    MeetingCreateResponse,
    MeetingStatus,
    MinutesResponse,
    PipelineStep,
)
from app.services.pipeline import PipelineDeps, download_name, run_pipeline
from app.services.transcript_parser import TEXT_EXTENSIONS
from app.services.transcription import AUDIO_EXTENSIONS

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

# 処理中のまま一定時間更新がなければ、止まったとみなして再開を許可する
STALE_AFTER = timedelta(minutes=20)


def _to_meeting(row: dict[str, Any]) -> Meeting:
    return Meeting.model_validate({**row, "participants": row.get("participants") or []})


def _own_meeting(repo: Repository, meeting_id: str, user_id: str) -> dict[str, Any]:
    try:
        uuid.UUID(meeting_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会議が見つかりません。")
    meeting = repo.get_meeting(meeting_id, user_id)
    if meeting is None:  # 他人の会議も「存在しない」として扱う
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会議が見つかりません。")
    return meeting


def validate_upload(body: MeetingCreate, settings: Settings) -> str:
    """ファイル形式・容量をチェックし、拡張子を返す。"""
    ext = Path(body.file_name).suffix.lower().lstrip(".")
    if body.input_type == "text":
        if ext not in TEXT_EXTENSIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ファイル形式が正しくありません。文字起こしは TXT / VTT / SRT に対応しています。")
        limit = settings.max_text_bytes
    else:
        # 動画はブラウザ側で音声に変換してからアップロードされる
        if ext not in AUDIO_EXTENSIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ファイル形式が正しくありません。音声は MP3 / M4A / WAV / WebM / OGG などに対応しています。")
        limit = settings.max_audio_bytes
    if body.file_size > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"ファイルサイズが上限（{limit // (1024 * 1024)}MB）を超えています。",
        )
    return ext


@router.post("", response_model=MeetingCreateResponse, status_code=status.HTTP_201_CREATED)
def create_meeting(
    body: MeetingCreate,
    user_id: str = Depends(current_user_id),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> MeetingCreateResponse:
    ext = validate_upload(body, settings)
    meeting_id = str(uuid.uuid4())
    path = f"{user_id}/{meeting_id}/source.{ext}"
    row = repo.create_meeting(user_id, body, path, meeting_id)
    token = repo.create_upload_url(path)
    meeting = repo.get_meeting(meeting_id, user_id) or row
    return MeetingCreateResponse(meeting=_to_meeting(meeting), upload_path=path, upload_token=token)


@router.get("", response_model=list[Meeting])
def list_meetings(user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo)) -> list[Meeting]:
    return [_to_meeting(r) for r in repo.list_meetings(user_id)]


@router.get("/{meeting_id}", response_model=Meeting)
def get_meeting(meeting_id: str, user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo)) -> Meeting:
    return _to_meeting(_own_meeting(repo, meeting_id, user_id))


@router.post("/{meeting_id}/process", response_model=Meeting, status_code=status.HTTP_202_ACCEPTED)
def process_meeting(
    meeting_id: str,
    background: BackgroundTasks,
    user_id: str = Depends(current_user_id),
    repo: Repository = Depends(get_repo),
    deps: PipelineDeps = Depends(get_pipeline_deps),
) -> Meeting:
    """アップロード完了後の処理開始。ERROR の場合は失敗したステップから再開する（再試行）。"""
    _own_meeting(repo, meeting_id, user_id)
    stale_before = datetime.now(timezone.utc) - STALE_AFTER
    if not repo.claim_for_processing(meeting_id, [MeetingStatus.UPLOADED, MeetingStatus.ERROR], stale_before):
        raise HTTPException(status.HTTP_409_CONFLICT, "この会議はすでに処理中か、処理が完了しています。")
    background.add_task(run_pipeline, deps, meeting_id)
    return _to_meeting(_own_meeting(repo, meeting_id, user_id))


@router.get("/{meeting_id}/minutes", response_model=MinutesResponse)
def get_minutes(meeting_id: str, user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo)) -> MinutesResponse:
    _own_meeting(repo, meeting_id, user_id)
    row = repo.get_minutes(meeting_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "議事録はまだ生成されていません。")
    return MinutesResponse.model_validate(row)


@router.get("/{meeting_id}/files/{file_type}", response_model=FileUrlResponse)
def get_file_url(
    meeting_id: str, file_type: FileType, user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo)
) -> FileUrlResponse:
    meeting = _own_meeting(repo, meeting_id, user_id)
    files = {f["file_type"]: f for f in repo.list_files(meeting_id)}
    if file_type not in files:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ファイルはまだ生成されていません。")
    name = download_name(meeting, file_type)
    return FileUrlResponse(url=repo.signed_download_url(files[file_type]["file_path"], name), file_name=name)


@router.post("/{meeting_id}/dropbox", response_model=Meeting, status_code=status.HTTP_202_ACCEPTED)
def save_to_dropbox(
    meeting_id: str,
    background: BackgroundTasks,
    user_id: str = Depends(current_user_id),
    repo: Repository = Depends(get_repo),
    deps: PipelineDeps = Depends(get_pipeline_deps),
) -> Meeting:
    """手動でDropboxへ保存（未連携で止まっていた会議、または再保存）。"""
    meeting = _own_meeting(repo, meeting_id, user_id)
    if repo.get_dropbox_connection(user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dropboxが連携されていません。設定画面から連携してください。")
    allowed = [MeetingStatus.GENERATED, MeetingStatus.COMPLETED]
    if meeting["status"] == MeetingStatus.ERROR and meeting.get("error_step") == PipelineStep.DROPBOX:
        allowed.append(MeetingStatus.ERROR)
    stale_before = datetime.now(timezone.utc) - STALE_AFTER
    if not repo.claim_for_processing(meeting_id, allowed, stale_before):
        raise HTTPException(status.HTTP_409_CONFLICT, "議事録の生成が完了してから保存してください。")
    background.add_task(run_pipeline, deps, meeting_id, only=PipelineStep.DROPBOX)
    return _to_meeting(_own_meeting(repo, meeting_id, user_id))
