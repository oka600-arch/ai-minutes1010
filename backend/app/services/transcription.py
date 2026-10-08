"""音声の文字起こし（OpenAI）。

OpenAI の文字起こし API は 1 ファイル 25MB までなので、ffmpeg でモノラル・低ビットレートに
変換し、10 分ごとに分割して順番に文字起こしし、結合する。
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

AUDIO_EXTENSIONS = {"mp3", "m4a", "wav", "webm", "ogg", "mp4", "mpeg", "mpga", "aac", "flac"}
SEGMENT_SECONDS = 600


class TranscriptionError(Exception):
    pass


class AudioClient(Protocol):
    audio: Any


def split_audio(source: Path, workdir: Path) -> list[Path]:
    """音声をモノラル 16kHz・32kbps の mp3 に変換しつつ、10 分ごとに分割する。"""
    pattern = workdir / "segment_%03d.mp3"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k",
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-reset_timestamps", "1",
        str(pattern),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    except FileNotFoundError as exc:
        raise TranscriptionError("サーバーに ffmpeg がインストールされていません。") from exc
    except subprocess.CalledProcessError as exc:
        raise TranscriptionError("音声ファイルを読み込めませんでした。ファイルが壊れているか、対応していない形式です。") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscriptionError("音声の変換に時間がかかりすぎたため中断しました。") from exc
    segments = sorted(workdir.glob("segment_*.mp3"))
    if not segments:
        raise TranscriptionError("音声データが見つかりませんでした。")
    return segments


def transcribe_audio(client: AudioClient, model: str, source: Path, participants: list[str]) -> str:
    # 参加者名をヒントとして渡すと、人名の認識精度が上がる
    prompt = f"日本語のビジネス会議です。参加者：{'、'.join(participants)}" if participants else "日本語のビジネス会議です。"
    texts: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for segment in split_audio(source, Path(tmp)):
            try:
                with segment.open("rb") as f:
                    result = client.audio.transcriptions.create(
                        model=model, file=f, language="ja", prompt=prompt, response_format="text",
                    )
            except Exception as exc:
                raise TranscriptionError("音声認識APIの呼び出しに失敗しました。") from exc
            text = result if isinstance(result, str) else getattr(result, "text", "")
            if text.strip():
                texts.append(text.strip())
    if not texts:
        raise TranscriptionError("音声から発言を認識できませんでした。")
    return "\n".join(texts)
