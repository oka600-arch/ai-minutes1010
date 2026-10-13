"""FastAPI の依存関係（認証・リポジトリ・文字起こし／AI解析の部品）。"""

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.db import Repository
from app.services.analysis import Analyzer, GeminiAnalyzer, OllamaAnalyzer
from app.services.pipeline import PipelineDeps
from app.services.transcription import Transcriber, WhisperTranscriber


@lru_cache
def _repo() -> Repository:
    return Repository()


def get_repo() -> Repository:
    try:
        return _repo()
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "サーバーのデータベース設定が不足しています。") from exc


@lru_cache
def get_transcriber() -> Transcriber:
    # モデルは初回の文字起こし時に読み込む（起動を速くするため）。プロセス内で 1 つを使い回す
    s = get_settings()
    return WhisperTranscriber(s.whisper_model, s.whisper_device, s.whisper_compute_type, s.whisper_cpu_threads, s.whisper_beam_size)


@lru_cache
def get_analyzer() -> Analyzer:
    # キー未設定でも起動できるようにし、実際の解析時にエラーメッセージを出す
    s = get_settings()
    if s.analysis_provider.lower() == "ollama":
        return OllamaAnalyzer(s.ollama_url, s.ollama_model)
    return GeminiAnalyzer(s.gemini_api_key, s.gemini_model)


def get_pipeline_deps(
    repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)
) -> PipelineDeps:
    return PipelineDeps(repo=repo, transcriber=get_transcriber(), analyzer=get_analyzer(), settings=settings)


def current_user_id(
    authorization: str | None = Header(default=None), repo: Repository = Depends(get_repo)
) -> str:
    """Supabase Auth のアクセストークンを検証し、ユーザー ID を返す。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインが必要です。")
    user_id = repo.user_id_from_token(authorization.split(" ", 1)[1].strip())
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインの有効期限が切れました。再度ログインしてください。")
    return user_id
