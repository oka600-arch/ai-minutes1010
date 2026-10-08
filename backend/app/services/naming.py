"""ファイル名・フォルダ名の規則（設計書23章：YYYY-MM-DD_会議名）。"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
# Dropbox・Windows で使えない文字
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def to_jst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def sanitize(name: str) -> str:
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".")
    return cleaned[:80] or "会議"


def base_name(meeting_name: str, meeting_datetime: datetime) -> str:
    return f"{to_jst(meeting_datetime):%Y-%m-%d}_{sanitize(meeting_name)}"


def format_datetime_ja(dt: datetime) -> str:
    return f"{to_jst(dt):%Y/%m/%d %H:%M}"
