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
    MinutesUpdate,
    PipelineStep,
)
from app.services.minutes_types import MinutesDataError, describe_types, get_type, normalize
from app.services.pipeline import PipelineDeps, StepError, download_name, generate_documents, run_pipeline
from app.services.transcript_parser import TEXT_EXTENSIONS
from app.services.transcription import AUDIO_EXTENSIONS

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
types_router = APIRouter(prefix="/api/minutes-types", tags=["meetings"])

IN_PROGRESS = {MeetingStatus.TRANSCRIBING, MeetingStatus.ANALYZING, MeetingStatus.GENERATING, MeetingStatus.UPLOADING}


@types_router.get("")
def list_minutes_types() -> list[dict[str, Any]]:
    """議事録の種類と項目の一覧（画面の選択肢・表示・編集フォームに使う）。"""
    return describe_types()

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


def _minutes_response(meeting: dict[str, Any], row: dict[str, Any]) -> MinutesResponse:
    t = get_type(row.get("minutes_type") or meeting.get("minutes_type"))
    return MinutesResponse(
        meeting_id=meeting["id"], minutes_type=t.key, data=normalize(t, row.get("data") or {}),
        ai_model=row.get("ai_model"), edited_at=row.get("edited_at"),
    )


@router.get("/{meeting_id}/minutes", response_model=MinutesResponse)
def get_minutes(meeting_id: str, user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo)) -> MinutesResponse:
    meeting = _own_meeting(repo, meeting_id, user_id)
    row = repo.get_minutes(meeting_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "議事録はまだ生成されていません。")
    return _minutes_response(meeting, row)


@router.put("/{meeting_id}/minutes", response_model=MinutesResponse)
def update_minutes(
    meeting_id: str,
    body: MinutesUpdate,
    background: BackgroundTasks,
    user_id: str = Depends(current_user_id),
    repo: Repository = Depends(get_repo),
    deps: PipelineDeps = Depends(get_pipeline_deps),
) -> MinutesResponse:
    """画面で編集した議事録を保存し、Word/PDF を作り直す。Dropbox に保存済みなら同じフォルダに上書き保存する。"""
    meeting = _own_meeting(repo, meeting_id, user_id)
    if MeetingStatus(meeting["status"]) in IN_PROGRESS:
        raise HTTPException(status.HTTP_409_CONFLICT, "処理中のため編集できません。処理が終わってから保存してください。")
    row = repo.get_minutes(meeting_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "議事録はまだ生成されていません。")
    t = get_type(row.get("minutes_type") or meeting.get("minutes_type"))
    try:
        data = normalize(t, body.data)
    except MinutesDataError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    repo.update_minutes_data(meeting_id, data)
    try:
        generate_documents(repo, meeting)
    except StepError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"{exc} 編集内容は保存されています。") from exc
    if meeting["status"] == MeetingStatus.ERROR and meeting.get("error_step") == PipelineStep.GENERATE:
        repo.set_status(meeting_id, MeetingStatus.GENERATED)

    # Dropbox に保存済みの会議は、編集後のファイルで上書きする
    if meeting.get("dropbox_folder_path") and repo.get_dropbox_connection(user_id):
        stale_before = datetime.now(timezone.utc) - STALE_AFTER
        if repo.claim_for_processing(meeting_id, [MeetingStatus.GENERATED, MeetingStatus.COMPLETED, MeetingStatus.ERROR], stale_before):
            background.add_task(run_pipeline, deps, meeting_id, only=PipelineStep.DROPBOX)
    return _minutes_response(meeting, repo.get_minutes(meeting_id) or row)


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
