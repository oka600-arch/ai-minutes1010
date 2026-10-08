"""FastAPI の依存関係（認証・リポジトリ・OpenAI クライアント）。"""

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status
from openai import OpenAI

from app.config import Settings, get_settings
from app.db import Repository
from app.services.pipeline import PipelineDeps


@lru_cache
def _repo() -> Repository:
    return Repository()


def get_repo() -> Repository:
    try:
        return _repo()
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "サーバーのデータベース設定が不足しています。") from exc


@lru_cache
def get_openai() -> OpenAI:
    s = get_settings()
    # キー未設定でも起動できるようにし、実際の呼び出し時にエラーメッセージを出す
    return OpenAI(api_key=s.openai_api_key or "not-configured", max_retries=2, timeout=600)


def get_pipeline_deps(
    repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)
) -> PipelineDeps:
    return PipelineDeps(repo=repo, openai=get_openai(), settings=settings)


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
