import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.services import transcription
from app.services.transcription import TranscriptionError, WhisperTranscriber

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が必要")


class FakeWhisperModel:
    """faster_whisper.WhisperModel の代替（モデルをダウンロードせずにテストするため）。"""

    instances: list["FakeWhisperModel"] = []

    def __init__(self, size, **kwargs):
        self.size, self.kwargs, self.calls = size, kwargs, []
        FakeWhisperModel.instances.append(self)

    def transcribe(self, path, **kwargs):
        self.calls.append({"path": path, **kwargs})
        texts = [" 本日の議題は新商品です。", " ", "A案で進めましょう。"]
        return (SimpleNamespace(text=t) for t in texts), SimpleNamespace(duration=3.0)


def _tone(tmp_path, name="tone.webm"):
    src = tmp_path / name
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(src)], check=True)
    return src


def test_audio_is_converted_and_transcribed_with_participant_hint(tmp_path):
    FakeWhisperModel.instances.clear()
    t = WhisperTranscriber("small", model_factory=FakeWhisperModel)
    assert t.transcribe(_tone(tmp_path), ["山田", "佐藤"]) == "本日の議題は新商品です。\nA案で進めましょう。"
    model = FakeWhisperModel.instances[0]
    assert model.size == "small" and model.kwargs["compute_type"] == "int8" and model.kwargs["device"] == "cpu"
    call = model.calls[0]
    assert call["path"].endswith(".wav")  # ffmpeg で WAV に変換してから渡す
    assert call["language"] == "ja" and "山田、佐藤" in call["initial_prompt"] and call["vad_filter"] is True

    t.transcribe(_tone(tmp_path, "second.m4a"), [])
    assert len(FakeWhisperModel.instances) == 1  # モデルは使い回す


def test_progress_is_reported_during_long_transcription(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription, "PROGRESS_INTERVAL", 0)
    ticks: list[int] = []
    WhisperTranscriber(model_factory=FakeWhisperModel).transcribe(_tone(tmp_path), [], lambda: ticks.append(1))
    assert len(ticks) == 3


def test_broken_audio_raises(tmp_path):
    src = tmp_path / "broken.mp3"
    src.write_bytes(b"not audio")
    with pytest.raises(TranscriptionError, match="読み込めません"):
        WhisperTranscriber(model_factory=FakeWhisperModel).transcribe(src, [])


def test_model_load_failure_is_reported(tmp_path):
    def broken_factory(*args, **kwargs):
        raise OSError("download failed")

    with pytest.raises(TranscriptionError, match="モデルを読み込めません"):
        WhisperTranscriber(model_factory=broken_factory).transcribe(_tone(tmp_path), [])


def test_silence_only_raises(tmp_path):
    class Silent(FakeWhisperModel):
        def transcribe(self, path, **kwargs):
            return iter([]), SimpleNamespace(duration=3.0)

    with pytest.raises(TranscriptionError, match="認識できません"):
        WhisperTranscriber(model_factory=Silent).transcribe(_tone(tmp_path), [])
