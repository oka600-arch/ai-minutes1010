import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.db import Repository
from app.deps import current_user_id, get_repo
from app.schemas import DropboxConnectResponse, DropboxStatus
from app.services import dropbox_service
from app.services.crypto import TokenCryptoError, decrypt_token, encrypt_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dropbox", tags=["dropbox"])


def _configured(s: Settings) -> bool:
    return bool(s.dropbox_app_key and s.dropbox_app_secret and s.token_encryption_key)


@router.get("/status", response_model=DropboxStatus)
def dropbox_status(
    user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)
) -> DropboxStatus:
    conn = repo.get_dropbox_connection(user_id)
    return DropboxStatus(connected=conn is not None, email=conn.get("dropbox_email") if conn else None, configured=_configured(settings))


@router.get("/connect", response_model=DropboxConnectResponse)
def dropbox_connect(
    user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)
) -> DropboxConnectResponse:
    if not _configured(settings):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "サーバーにDropboxアプリの設定がありません。管理者に連絡してください。")
    start = dropbox_service.start_oauth(settings.dropbox_app_key, settings.dropbox_redirect_uri)
    repo.save_oauth_state(start.state, user_id, start.code_verifier)
    return DropboxConnectResponse(authorize_url=start.authorize_url)


@router.get("/callback")
def dropbox_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Dropbox の認可画面から戻ってくる先。ブラウザのリダイレクトなので、結果は設定画面へ渡す。"""

    def back(result: str) -> RedirectResponse:
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/settings?{urlencode({'dropbox': result})}", status_code=302)

    if error or not state or not code:
        return back("cancelled")
    saved = repo.pop_oauth_state(state)
    if saved is None:
        return back("expired")
    try:
        result = dropbox_service.finish_oauth(
            settings.dropbox_app_key, settings.dropbox_app_secret, settings.dropbox_redirect_uri, code, saved["code_verifier"]
        )
        repo.save_dropbox_connection(
            saved["user_id"], result.account_id, result.email, encrypt_token(result.refresh_token, settings.token_encryption_key)
        )
    except (dropbox_service.DropboxServiceError, TokenCryptoError) as exc:
        logger.warning("dropbox oauth failed: %s", type(exc).__name__)
        return back("error")
    return back("connected")


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def dropbox_disconnect(
    user_id: str = Depends(current_user_id), repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)
) -> None:
    conn = repo.get_dropbox_connection(user_id)
    if conn is None:
        return
    try:
        token = decrypt_token(conn["refresh_token_encrypted"], settings.token_encryption_key)
        dropbox_service.revoke(settings.dropbox_app_key, settings.dropbox_app_secret, token)
    except TokenCryptoError:
        pass
    repo.delete_dropbox_connection(user_id)
