import shutil
import subprocess

import pytest

from app.services.transcription import TranscriptionError, transcribe_audio
from tests.conftest import FakeOpenAI

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が必要")


def test_audio_is_converted_and_sent_with_participant_hint(tmp_path):
    src = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(src)], check=True)
    client = FakeOpenAI(transcript="山田：テストです。")
    assert transcribe_audio(client, "gpt-4o-transcribe", src, ["山田", "佐藤"]) == "山田：テストです。"
    call = client.calls[0]
    assert call["language"] == "ja" and "山田、佐藤" in call["prompt"]


def test_broken_audio_raises(tmp_path):
    src = tmp_path / "broken.mp3"
    src.write_bytes(b"not audio")
    with pytest.raises(TranscriptionError):
        transcribe_audio(FakeOpenAI(), "gpt-4o-transcribe", src, [])
