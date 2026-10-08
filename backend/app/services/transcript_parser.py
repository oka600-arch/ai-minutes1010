"""TXT / VTT / SRT の文字起こしファイルを「話者：発言」形式のプレーンテキストに整形する。"""

import re

from charset_normalizer import from_bytes

TEXT_EXTENSIONS = {"txt", "vtt", "srt"}

_TIMESTAMP_LINE = re.compile(
    r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}.*$"
)
_VOICE_TAG = re.compile(r"^<v(?:\.[^\s>]+)?\s+([^>]+)>(.*)$")
_ANY_TAG = re.compile(r"</?[^>]+>")
# Zoom の VTT は「山田 太郎: 発言」の形式
_ZOOM_SPEAKER = re.compile(r"^([^:：<>]{1,40})[:：]\s*(.+)$")


class TranscriptParseError(ValueError):
    pass


def decode_text(data: bytes) -> str:
    """UTF-8（BOM付き含む）を優先し、だめなら文字コードを推定する（Shift_JIS の TXT 対策）。"""
    if not data.strip():
        raise TranscriptParseError("ファイルが空です。")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    for encoding in ("cp932", "euc_jp"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    best = from_bytes(data).best()
    if best is None:
        raise TranscriptParseError("ファイルの文字コードを判定できませんでした。")
    return str(best)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _merge_same_speaker(lines: list[tuple[str | None, str]]) -> str:
    """字幕は1発言が細切れになるので、同じ話者の連続行を1行にまとめる。"""
    merged: list[tuple[str | None, str]] = []
    for speaker, text in lines:
        if merged and merged[-1][0] == speaker and speaker is not None:
            merged[-1] = (speaker, merged[-1][1] + text)
        else:
            merged.append((speaker, text))
    return "\n".join(f"{s}：{t}" if s else t for s, t in merged)


def _parse_cues(text: str) -> str:
    """字幕ファイルを空行区切りのブロックに分け、タイムスタンプ行より後ろを本文として読む。
    タイムスタンプのないブロック（WEBVTT ヘッダー・NOTE・STYLE 等）と、
    タイムスタンプ行より前の行（キュー ID・SRT の連番）は捨てる。"""
    lines: list[tuple[str | None, str]] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n\s*\n", normalized):
        rows = [r.strip() for r in block.split("\n") if r.strip()]
        ts_index = next((i for i, r in enumerate(rows) if _TIMESTAMP_LINE.match(r)), None)
        if ts_index is None:
            continue
        for line in rows[ts_index + 1:]:
            speaker: str | None = None
            voice = _VOICE_TAG.match(line)
            if voice:
                speaker, line = voice.group(1).strip(), voice.group(2)
            line = _ANY_TAG.sub("", line).strip()
            if speaker is None:
                zoom = _ZOOM_SPEAKER.match(line)
                if zoom:
                    speaker, line = zoom.group(1).strip(), zoom.group(2).strip()
            if line:
                lines.append((speaker, line))
    if not lines:
        raise TranscriptParseError("文字起こしの本文が見つかりませんでした。")
    return _merge_same_speaker(lines)


def parse_transcript(data: bytes, extension: str) -> str:
    ext = extension.lower().lstrip(".")
    if ext not in TEXT_EXTENSIONS:
        raise TranscriptParseError(f"対応していないファイル形式です（.{ext}）。")
    text = decode_text(data)
    if ext == "txt":
        result = _normalize(text)
        if not result:
            raise TranscriptParseError("ファイルが空です。")
        return result
    return _parse_cues(text)
