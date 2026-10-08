"""議事録生成の処理パイプライン。

文字起こし → AI解析 → Word/PDF生成 → Dropbox保存 を順に実行し、ステータスを更新する。
失敗したら ERROR と error_step を保存し、再試行時は error_step から再開する。
ログには会議 ID と例外の種類だけを出し、会議内容は出力しない（設計書26章）。
"""

import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.schemas import MeetingInfo, MeetingStatus, MinutesData, PipelineStep
from app.services.analysis import AnalysisError, analyze_transcript
from app.services.crypto import TokenCryptoError, decrypt_token
from app.services.docx_builder import DocxBuildError, build_docx
from app.services.dropbox_service import (
    DropboxAuthExpired,
    DropboxServiceError,
    UploadFile,
    folder_path_for,
    upload_files,
)
from app.services.naming import base_name
from app.services.pdf_builder import PdfBuildError, build_pdf
from app.services.transcript_parser import TranscriptParseError, parse_transcript
from app.services.transcription import TranscriptionError, transcribe_audio

logger = logging.getLogger(__name__)

STEP_ORDER = [PipelineStep.TRANSCRIBE, PipelineStep.ANALYZE, PipelineStep.GENERATE, PipelineStep.DROPBOX]
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class StepError(Exception):
    """ユーザーに表示してよいメッセージを持つ例外。"""


@dataclass
class PipelineDeps:
    repo: Any  # app.db.Repository と同じメソッドを持つオブジェクト
    openai: Any  # openai.OpenAI
    settings: Settings


def start_step_for(meeting: dict[str, Any]) -> PipelineStep:
    """現在のステータスから、どのステップから始めるかを決める。"""
    status = MeetingStatus(meeting["status"])
    if status == MeetingStatus.ERROR and meeting.get("error_step"):
        return PipelineStep(meeting["error_step"])
    return {
        MeetingStatus.UPLOADED: PipelineStep.TRANSCRIBE,
        MeetingStatus.TRANSCRIBING: PipelineStep.TRANSCRIBE,
        MeetingStatus.TRANSCRIBED: PipelineStep.ANALYZE,
        MeetingStatus.ANALYZING: PipelineStep.ANALYZE,
        MeetingStatus.GENERATING: PipelineStep.GENERATE,
        MeetingStatus.GENERATED: PipelineStep.DROPBOX,
        MeetingStatus.UPLOADING: PipelineStep.DROPBOX,
    }.get(status, PipelineStep.TRANSCRIBE)


def meeting_info(meeting: dict[str, Any]) -> MeetingInfo:
    return MeetingInfo(
        meeting_name=meeting["meeting_name"],
        meeting_datetime=datetime.fromisoformat(meeting["meeting_datetime"]),
        meeting_tool=meeting["meeting_tool"],
        participants=[p["name"] for p in meeting.get("participants") or []],
    )


def output_dir(meeting: dict[str, Any]) -> str:
    return f"{meeting['user_id']}/{meeting['id']}"


def run_pipeline(deps: PipelineDeps, meeting_id: str, start: PipelineStep | None = None, only: PipelineStep | None = None) -> None:
    """バックグラウンドで呼ばれる。例外は外に出さず、すべて ERROR ステータスとして記録する。"""
    repo = deps.repo
    meeting = repo.get_meeting(meeting_id)
    if meeting is None:
        return
    first = only or start or start_step_for(meeting)
    steps = [only] if only else STEP_ORDER[STEP_ORDER.index(first):]

    for step in steps:
        try:
            if step == PipelineStep.TRANSCRIBE:
                _transcribe(deps, meeting)
            elif step == PipelineStep.ANALYZE:
                _analyze(deps, meeting)
            elif step == PipelineStep.GENERATE:
                _generate(deps, meeting)
            elif step == PipelineStep.DROPBOX:
                _save_to_dropbox(deps, meeting)
            meeting = repo.get_meeting(meeting_id) or meeting
        except StepError as exc:
            logger.warning("meeting %s failed at %s: %s", meeting_id, step, type(exc.__cause__).__name__)
            repo.set_error(meeting_id, step, str(exc))
            return
        except Exception as exc:
            logger.exception("meeting %s unexpected error at %s (%s)", meeting_id, step, type(exc).__name__)
            repo.set_error(meeting_id, step, "予期しないエラーが発生しました。再試行してください。")
            return


# ---------------------------------------------------------------- 各ステップ


def _transcribe(deps: PipelineDeps, meeting: dict[str, Any]) -> None:
    repo, s = deps.repo, deps.settings
    repo.set_status(meeting["id"], MeetingStatus.TRANSCRIBING)
    path = meeting.get("source_file_path")
    if not path:
        raise StepError("アップロードされたファイルが見つかりません。もう一度アップロードしてください。")
    ext = Path(meeting.get("source_file_name") or path).suffix.lower().lstrip(".")

    try:
        data = repo.download("uploads", path)
    except Exception as exc:
        raise StepError("アップロードされたファイルを取得できませんでした。もう一度アップロードしてください。") from exc

    if meeting["input_type"] == "text":
        try:
            text = parse_transcript(data, ext)
        except TranscriptParseError as exc:
            raise StepError(str(exc)) from exc
        source_format = ext
    else:
        if not s.openai_api_key:
            raise StepError("OpenAI APIキーが設定されていないため、音声を文字起こしできません。")
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / f"source.{ext or 'bin'}"
            audio_path.write_bytes(data)
            try:
                text = transcribe_audio(deps.openai, s.openai_transcribe_model, audio_path, meeting_info(meeting).participants)
            except TranscriptionError as exc:
                raise StepError(str(exc)) from exc
        source_format = "audio"

    if len(text) > s.max_transcript_chars:
        raise StepError(f"文字起こしが長すぎます（{s.max_transcript_chars:,}文字まで）。会議を分けてアップロードしてください。")

    repo.save_transcript(meeting["id"], source_format, None, text)
    transcript_path = f"{output_dir(meeting)}/transcript.txt"
    repo.upload_output(transcript_path, text.encode("utf-8"), "text/plain; charset=utf-8")
    repo.save_file(meeting["id"], "transcript", "transcript.txt", transcript_path)

    # 元ファイルは不要になったので削除する（一時ファイルを必要以上に保存しない）
    try:
        repo.remove("uploads", path)
        repo.update_meeting(meeting["id"], source_file_path=None)
    except Exception:
        logger.warning("meeting %s: failed to remove source file", meeting["id"])

    repo.set_status(meeting["id"], MeetingStatus.TRANSCRIBED)


def _analyze(deps: PipelineDeps, meeting: dict[str, Any]) -> None:
    repo, s = deps.repo, deps.settings
    repo.set_status(meeting["id"], MeetingStatus.ANALYZING)
    if not s.openai_api_key:
        raise StepError("OpenAI APIキーが設定されていないため、AI解析を実行できません。")
    transcript = repo.get_transcript(meeting["id"])
    if not transcript:
        raise StepError("文字起こしデータが見つかりません。最初からやり直してください。")
    try:
        minutes = analyze_transcript(deps.openai, s.openai_analysis_model, meeting_info(meeting), transcript)
    except AnalysisError as exc:
        raise StepError(str(exc)) from exc
    repo.save_minutes(meeting["id"], minutes, s.openai_analysis_model)
    repo.set_status(meeting["id"], MeetingStatus.GENERATING)


def _generate(deps: PipelineDeps, meeting: dict[str, Any]) -> None:
    repo = deps.repo
    repo.set_status(meeting["id"], MeetingStatus.GENERATING)
    row = repo.get_minutes(meeting["id"])
    if row is None:
        raise StepError("議事録データが見つかりません。AI解析からやり直してください。")
    minutes = MinutesData.model_validate(row)
    info = meeting_info(meeting)
    try:
        docx = build_docx(info, minutes)
        pdf = build_pdf(info, minutes)
    except (DocxBuildError, PdfBuildError) as exc:
        raise StepError(str(exc)) from exc
    d = output_dir(meeting)
    repo.upload_output(f"{d}/meeting_minutes.docx", docx, DOCX_TYPE)
    repo.save_file(meeting["id"], "docx", "meeting_minutes.docx", f"{d}/meeting_minutes.docx")
    repo.upload_output(f"{d}/meeting_minutes.pdf", pdf, "application/pdf")
    repo.save_file(meeting["id"], "pdf", "meeting_minutes.pdf", f"{d}/meeting_minutes.pdf")
    repo.set_status(meeting["id"], MeetingStatus.GENERATED)


def _save_to_dropbox(deps: PipelineDeps, meeting: dict[str, Any]) -> None:
    repo, s = deps.repo, deps.settings
    conn = repo.get_dropbox_connection(meeting["user_id"])
    if conn is None or not s.dropbox_app_key:
        # 未連携ならエラーにせず GENERATED のまま止める（画面に「連携して保存」を表示）
        repo.set_status(meeting["id"], MeetingStatus.GENERATED)
        return
    repo.set_status(meeting["id"], MeetingStatus.UPLOADING)

    try:
        refresh_token = decrypt_token(conn["refresh_token_encrypted"], s.token_encryption_key)
    except TokenCryptoError as exc:
        raise StepError(str(exc)) from exc

    files_by_type = {f["file_type"]: f for f in repo.list_files(meeting["id"])}
    if not {"transcript", "docx", "pdf"} <= files_by_type.keys():
        raise StepError("保存するファイルが揃っていません。Word/PDF生成からやり直してください。")
    uploads: list[UploadFile] = []
    for file_type in ("transcript", "docx", "pdf"):
        try:
            content = repo.download("outputs", files_by_type[file_type]["file_path"])
        except Exception as exc:
            raise StepError("保存するファイルを取得できませんでした。") from exc
        uploads.append(UploadFile(files_by_type[file_type]["file_name"], content))

    existing = meeting.get("dropbox_folder_path")
    desired = existing or folder_path_for(s.dropbox_root_folder, meeting["meeting_name"], datetime.fromisoformat(meeting["meeting_datetime"]))
    try:
        folder, paths = upload_files(
            s.dropbox_app_key, s.dropbox_app_secret, refresh_token, desired, uploads, reuse_folder=bool(existing)
        )
    except DropboxAuthExpired as exc:
        repo.delete_dropbox_connection(meeting["user_id"])
        raise StepError(str(exc)) from exc
    except DropboxServiceError as exc:
        raise StepError(str(exc)) from exc

    repo.update_meeting(meeting["id"], dropbox_folder_path=folder)
    for file_type in ("transcript", "docx", "pdf"):
        name = files_by_type[file_type]["file_name"]
        repo.set_file_dropbox_path(meeting["id"], file_type, paths[name])
    repo.set_status(meeting["id"], MeetingStatus.COMPLETED)


def download_name(meeting: dict[str, Any], file_type: str) -> str:
    """ダウンロード時のファイル名：2026-10-08_営業定例会議_議事録.docx"""
    base = base_name(meeting["meeting_name"], datetime.fromisoformat(meeting["meeting_datetime"]))
    return {
        "docx": f"{base}_議事録.docx",
        "pdf": f"{base}_議事録.pdf",
        "transcript": f"{base}_文字起こし.txt",
    }[file_type]
