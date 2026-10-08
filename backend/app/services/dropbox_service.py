"""Dropbox 連携（ユーザーごとの OAuth 2.0 + PKCE、ファイル保存）。

アクセストークンは数時間で失効するため、リフレッシュトークンだけを暗号化して保存し、
SDK に渡して自動更新させる。
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

import dropbox
import httpx
from dropbox.exceptions import ApiError, AuthError
from dropbox.files import WriteMode

from app.services.naming import base_name, to_jst

AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


class DropboxServiceError(Exception):
    pass


class DropboxAuthExpired(DropboxServiceError):
    """ユーザーが連携を解除した等で、リフレッシュトークンが使えなくなった。"""


@dataclass
class OAuthStart:
    authorize_url: str
    state: str
    code_verifier: str


@dataclass
class OAuthResult:
    refresh_token: str
    account_id: str
    email: str | None


def start_oauth(app_key: str, redirect_uri: str) -> OAuthStart:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": app_key,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "token_access_type": "offline",  # リフレッシュトークンを受け取る
    }
    return OAuthStart(f"{AUTHORIZE_URL}?{urlencode(params)}", state, verifier)


def finish_oauth(app_key: str, app_secret: str, redirect_uri: str, code: str, code_verifier: str) -> OAuthResult:
    try:
        res = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "client_id": app_key,
                "client_secret": app_secret,
            },
            timeout=20,
        )
        res.raise_for_status()
        token = res.json()
    except httpx.HTTPError as exc:
        raise DropboxServiceError("Dropboxの認可に失敗しました。もう一度お試しください。") from exc
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise DropboxServiceError("Dropboxからリフレッシュトークンを取得できませんでした。")

    email = None
    try:
        with dropbox.Dropbox(oauth2_access_token=token["access_token"]) as dbx:
            email = dbx.users_get_current_account().email
    except Exception:
        pass  # メールアドレスは表示用なので、取れなくても連携は続行する
    return OAuthResult(refresh_token=refresh_token, account_id=token.get("account_id", ""), email=email)


def revoke(app_key: str, app_secret: str, refresh_token: str) -> None:
    try:
        with _client(app_key, app_secret, refresh_token) as dbx:
            dbx.auth_token_revoke()
    except Exception:
        pass  # すでに無効なら何もしない


def _client(app_key: str, app_secret: str, refresh_token: str) -> dropbox.Dropbox:
    return dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret, timeout=60)


def folder_path_for(root: str, meeting_name: str, meeting_datetime: datetime) -> str:
    """/AI議事録/2026/10月/2026-10-08_営業定例会議"""
    dt = to_jst(meeting_datetime)
    return f"{root.rstrip('/')}/{dt:%Y}/{dt.month}月/{base_name(meeting_name, meeting_datetime)}"


@dataclass
class UploadFile:
    name: str
    content: bytes


def upload_files(
    app_key: str,
    app_secret: str,
    refresh_token: str,
    desired_folder: str,
    files: list[UploadFile],
    *,
    reuse_folder: bool,
) -> tuple[str, dict[str, str]]:
    """フォルダを作成してファイルを保存し、サイズを照合して保存結果を確認する。

    reuse_folder=False のとき、同名フォルダが既にあれば末尾に _2, _3 … を付ける
    （同じ日に同じ名前の会議が複数ある場合）。再試行時は True で同じフォルダに上書きする。
    戻り値：（実際のフォルダパス, {ファイル名: Dropbox上のパス}）
    """
    try:
        with _client(app_key, app_secret, refresh_token) as dbx:
            folder = desired_folder if reuse_folder else _unique_folder(dbx, desired_folder)
            paths: dict[str, str] = {}
            for f in files:
                path = f"{folder}/{f.name}"
                meta = dbx.files_upload(f.content, path, mode=WriteMode.overwrite, mute=True)
                # 保存結果確認：サーバー上のサイズと一致するか
                if getattr(meta, "size", None) != len(f.content):
                    raise DropboxServiceError(f"{f.name} の保存結果を確認できませんでした。")
                paths[f.name] = meta.path_display or path
            return folder, paths
    except AuthError as exc:
        raise DropboxAuthExpired("Dropboxの連携が切れています。設定画面から再連携してください。") from exc
    except ApiError as exc:
        if "insufficient_space" in str(exc.error):
            raise DropboxServiceError("Dropboxの空き容量が不足しています。") from exc
        raise DropboxServiceError("Dropboxへの保存に失敗しました。") from exc
    except DropboxServiceError:
        raise
    except Exception as exc:
        raise DropboxServiceError("Dropboxへの保存に失敗しました。") from exc


def _exists(dbx: dropbox.Dropbox, path: str) -> bool:
    try:
        dbx.files_get_metadata(path)
        return True
    except ApiError as exc:
        if exc.error.is_path() and exc.error.get_path().is_not_found():
            return False
        raise


def _unique_folder(dbx: dropbox.Dropbox, folder: str) -> str:
    candidate, n = folder, 2
    while _exists(dbx, candidate):
        candidate = f"{folder}_{n}"
        n += 1
    return candidate
