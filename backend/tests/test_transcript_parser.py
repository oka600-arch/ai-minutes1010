import pytest

from app.services.transcript_parser import TranscriptParseError, parse_transcript
from tests.conftest import SAMPLE_DIR


def test_txt_sample_is_kept_line_by_line():
    data = (SAMPLE_DIR / "eigyo_teirei_2026-10-08.txt").read_bytes()
    text = parse_transcript(data, "txt")
    assert text.splitlines()[0].startswith("山田：はい、それでは")
    assert "1,500万円" in text


def test_vtt_sample_keeps_speakers_and_drops_timestamps():
    data = (SAMPLE_DIR / "eigyo_teirei_2026-10-08.vtt").read_bytes()
    text = parse_transcript(data, "vtt")
    assert "-->" not in text and "WEBVTT" not in text
    assert "佐藤：承知しました。10月15日までに送ります。" in text


def test_shift_jis_txt_is_decoded():
    data = "田中：来週までに資料を作成します。".encode("cp932")
    assert parse_transcript(data, "txt") == "田中：来週までに資料を作成します。"


def test_srt_and_consecutive_lines_of_same_speaker_are_merged():
    srt = "1\n00:00:01,000 --> 00:00:03,000\n山田: 資料は\n\n2\n00:00:03,000 --> 00:00:05,000\n山田: 来週までに\n\n3\n00:00:05,000 --> 00:00:06,000\n佐藤: はい\n"
    assert parse_transcript(srt.encode(), "srt") == "山田：資料は来週までに\n佐藤：はい"


def test_teams_style_voice_tags():
    vtt = "WEBVTT\n\nabc-123-def-456-ghi-789-jkl/12-0\n00:00:01.000 --> 00:00:03.000\n<v 山田 太郎>A案で進めましょう。</v>\n"
    assert parse_transcript(vtt.encode(), "vtt") == "山田 太郎：A案で進めましょう。"


@pytest.mark.parametrize("data,ext", [(b"", "txt"), (b"WEBVTT\n\n", "vtt"), (b"hello", "pdf")])
def test_invalid_inputs_raise(data, ext):
    with pytest.raises(TranscriptParseError):
        parse_transcript(data, ext)
