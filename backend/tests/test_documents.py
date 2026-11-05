from datetime import datetime
from io import BytesIO

import pytest
from docx import Document

from app.schemas import MeetingInfo
from app.services.docx_builder import build_docx
from app.services.dropbox_service import folder_path_for
from app.services.naming import JST, base_name
from app.services.minutes_types import MINUTES_TYPES, normalize
from app.services.pdf_builder import build_pdf
from tests.conftest import expected

INFO = MeetingInfo(meeting_name="営業部 定例会議", meeting_datetime=datetime(2026, 10, 8, 10, tzinfo=JST), meeting_tool="zoom", participants=["山田", "佐藤", "田中"])


def _texts(docx: bytes) -> tuple[str, list]:
    doc = Document(BytesIO(docx))
    return "\n".join(p.text for p in doc.paragraphs), doc.tables


def test_record_docx_has_editable_fields_in_header_and_sections():
    t = MINUTES_TYPES["record"]
    data = normalize(t, expected("record"))
    data["title"] = "営業部 定例会議（修正版）"  # 画面で書き換えたタイトルが反映される
    text, tables = _texts(build_docx(INFO, t, data))
    assert "会議記録（AI自動生成ベース資料）" in text
    header = {row.cells[0].text: row.cells[1].text for row in tables[0].rows}
    assert header["タイトル"] == "営業部 定例会議（修正版）"
    assert header["日時"] == "2026/10/08 10:00" and header["担当者"] == "山田"
    for heading in ("内容", "要約文", "詳細"):
        assert f"■ {heading}" in text
    assert "【決定事項】" in text and "来月の受注目標を1,500万円とする。" in text


def test_review_docx_has_causes_improvements_and_action_table():
    t = MINUTES_TYPES["review"]
    text, tables = _texts(build_docx(INFO, t, normalize(t, expected("review"))))
    assert "会議の振り返りまとめ" in text
    for heading in ("概要", "良かった点", "課題・問題点", "原因", "改善策", "今後のアクション"):
        assert f"■ {heading}" in text
    actions = tables[1]
    assert [c.text for c in actions.rows[0].cells] == ["タスク", "担当者", "期限"]
    assert actions.rows[1].cells[1].text == "高橋"


def test_daily_docx_sections():
    t = MINUTES_TYPES["daily"]
    text, _ = _texts(build_docx(INFO, t, normalize(t, expected("daily"))))
    for heading in ("出来事・取り組んだこと", "良かったこと", "気づき・学び", "困りごと・課題", "次にやること"):
        assert f"■ {heading}" in text


@pytest.mark.parametrize("type_key", ["record", "review", "daily"])
def test_pdf_is_generated_with_embedded_japanese_font(type_key):
    t = MINUTES_TYPES[type_key]
    pdf = build_pdf(INFO, t, normalize(t, expected(type_key)))
    assert pdf.startswith(b"%PDF")
    assert b"NotoSansJP" in pdf


@pytest.mark.parametrize("type_key", ["record", "review", "daily"])
def test_empty_minutes_still_render(type_key):
    t = MINUTES_TYPES[type_key]
    empty = normalize(t, {})
    assert build_docx(INFO, t, empty)
    assert build_pdf(INFO, t, empty).startswith(b"%PDF")


def test_names_follow_date_and_meeting_name_rule():
    assert base_name("営業/定例:会議", INFO.meeting_datetime) == "2026-10-08_営業_定例_会議"
    assert folder_path_for("/AI議事録", "営業定例会議", INFO.meeting_datetime) == "/AI議事録/2026/10月/2026-10-08_営業定例会議"
    # UTC で前日になる時刻でも、日本時間の日付を使う
    assert base_name("朝会", datetime.fromisoformat("2026-10-07T23:30:00+00:00")) == "2026-10-08_朝会"
