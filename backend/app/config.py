"""アプリ設定。値はすべて環境変数（.env）から読み込む。APIキーをコードに書かないこと。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # 文字起こし（faster-whisper。サーバー内で動かすので無料）
    # モデル：small（標準・速い）/ medium（より正確・約2〜3倍遅い）/ large-v3（最も正確・とても遅い）
    whisper_model: str = "small"
    whisper_device: str = "cpu"  # NVIDIA GPU があれば cuda
    whisper_compute_type: str = "int8"  # GPU なら float16
    whisper_cpu_threads: int = 0  # 0 は自動
    whisper_beam_size: int = 5  # 1 にすると速くなるが、精度が少し下がる

    # AI解析：gemini（Google Gemini API。無料枠あり）または ollama（ローカル LLM）
    analysis_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Dropbox（ユーザーごとの OAuth）
    dropbox_app_key: str = ""
    dropbox_app_secret: str = ""
    dropbox_redirect_uri: str = "http://localhost:8000/api/dropbox/callback"
    dropbox_root_folder: str = "/AI議事録"

    # Dropbox リフレッシュトークン暗号化用の鍵（Fernet）。生成方法は README を参照
    token_encryption_key: str = ""

    # フロントエンド
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    # 制限
    max_audio_bytes: int = 100 * 1024 * 1024
    max_text_bytes: int = 5 * 1024 * 1024
    max_transcript_chars: int = 200_000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
