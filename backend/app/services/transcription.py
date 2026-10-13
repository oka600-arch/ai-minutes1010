"""音声の文字起こし（faster-whisper。サーバーの中で動かすので、音声を外部の AI に送らず、利用料もかからない）。

ffmpeg でモノラル 16kHz の WAV に変換してから Whisper に渡す。GPU がない環境（CPU）を前提に
int8 で動かす。CPU では録音時間と同じくらいか、それ以上の時間がかかることがある。
"""

import logging
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {"mp3", "m4a", "wav", "webm", "ogg", "mp4", "mpeg", "mpga", "aac", "flac"}

# 進捗の通知間隔（秒）。長い文字起こしの途中で「止まった」と誤判定されないよう、定期的に知らせる
PROGRESS_INTERVAL = 60

ProgressCallback = Callable[[], None]


class TranscriptionError(Exception):
    pass


class Transcriber(Protocol):
    def check(self) -> str | None:
        """設定に問題があれば、画面に表示するメッセージを返す。"""

    def transcribe(self, source: Path, participants: list[str], on_progress: ProgressCallback | None = None) -> str: ...


def to_wav(source: Path, workdir: Path) -> Path:
    """音声・動画をモノラル 16kHz の WAV に変換する（Whisper の入力形式）。"""
    dest = workdir / "audio.wav"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    except FileNotFoundError as exc:
        raise TranscriptionError("サーバーに ffmpeg がインストールされていません。") from exc
    except subprocess.CalledProcessError as exc:
        raise TranscriptionError("音声ファイルを読み込めませんでした。ファイルが壊れているか、対応していない形式です。") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscriptionError("音声の変換に時間がかかりすぎたため中断しました。") from exc
    if not dest.exists() or dest.stat().st_size <= 44:  # 44 バイトは WAV ヘッダーだけ
        raise TranscriptionError("音声データが見つかりませんでした。")
    return dest


def initial_prompt(participants: list[str]) -> str:
    # 参加者名をヒントとして渡すと、人名の認識精度が上がる
    if participants:
        return f"日本語のビジネス会議です。参加者：{'、'.join(participants)}。"
    return "日本語のビジネス会議です。"


class WhisperTranscriber:
    """faster-whisper による文字起こし。モデルは初回利用時に読み込み、以後は使い回す。"""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        beam_size: int = 5,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.beam_size = beam_size
        self._model_factory = model_factory
        self._model: Any = None
        self._load_lock = threading.Lock()
        # CPU を使い切る処理なので、同時に複数の会議を文字起こしせず順番待ちにする
        self._run_lock = threading.Lock()

    def check(self) -> str | None:
        return None

    def _get_model(self) -> Any:
        with self._load_lock:
            if self._model is None:
                factory = self._model_factory
                if factory is None:
                    from faster_whisper import WhisperModel  # 重いので使うときだけ読み込む

                    factory = WhisperModel
                try:
                    self._model = factory(
                        self.model_size, device=self.device, compute_type=self.compute_type, cpu_threads=self.cpu_threads
                    )
                except Exception as exc:
                    raise TranscriptionError("文字起こしモデルを読み込めませんでした。サーバーの設定を確認してください。") from exc
            return self._model

    def transcribe(self, source: Path, participants: list[str], on_progress: ProgressCallback | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            wav = to_wav(source, Path(tmp))
            with self._run_lock:
                model = self._get_model()
                started = time.monotonic()
                last_notified = started
                texts: list[str] = []
                try:
                    segments, _info = model.transcribe(
                        str(wav),
                        language="ja",
                        beam_size=self.beam_size,
                        initial_prompt=initial_prompt(participants),
                        vad_filter=True,  # 無音部分を飛ばして速くし、無音中の誤認識も防ぐ
                        condition_on_previous_text=False,  # 同じ文の繰り返し（幻覚）を起こしにくくする
                    )
                    # segments はジェネレーターで、読み進めるたびに文字起こしが進む
                    for segment in segments:
                        text = segment.text.strip()
                        if text:
                            texts.append(text)
                        now = time.monotonic()
                        if on_progress and now - last_notified >= PROGRESS_INTERVAL:
                            on_progress()
                            last_notified = now
                except Exception as exc:
                    raise TranscriptionError("音声の文字起こし中にエラーが発生しました。") from exc
                logger.info("transcribed in %.0fs (model=%s)", time.monotonic() - started, self.model_size)
        if not texts:
            raise TranscriptionError("音声から発言を認識できませんでした。")
        return "\n".join(texts)
