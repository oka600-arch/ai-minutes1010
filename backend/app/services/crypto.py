"""Dropbox のリフレッシュトークンを DB に保存する前に暗号化する。"""

from cryptography.fernet import Fernet, InvalidToken


class TokenCryptoError(Exception):
    pass


def _fernet(key: str) -> Fernet:
    if not key:
        raise TokenCryptoError("TOKEN_ENCRYPTION_KEY が設定されていません。")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise TokenCryptoError("TOKEN_ENCRYPTION_KEY の形式が正しくありません。") from exc


def encrypt_token(token: str, key: str) -> str:
    return _fernet(key).encrypt(token.encode()).decode()


def decrypt_token(encrypted: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise TokenCryptoError("保存されたDropboxトークンを復号できませんでした。再連携してください。") from exc
