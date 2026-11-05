"""議事録の Word ファイルを生成する。"""

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.schemas import MeetingInfo
from app.services.minutes_types import FieldDef, MinutesTypeDef
from app.services.naming import format_datetime_ja

FONT_NAME = "游ゴシック"
TOOL_LABELS = {"zoom": "Zoom", "google_meet": "Google Meet", "teams": "Microsoft Teams", "other": "その他"}
DISCLAIMER = "本資料はAIが会議の文字起こしから自動生成したベース資料です。正式な議事録は内容を確認のうえ作成してください。"


class DocxBuildError(Exception):
    pass


def _set_font(run, size: float | None = None, bold: bool | None = None) -> None:
    run.font.name = FONT_NAME
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT_NAME)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold


def _shade(cell, hex_color: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    cell._element.get_or_add_tcPr().append(shd)


def _repeat_header(row) -> None:
    """表がページをまたぐとき、見出し行を次ページにも表示する。"""
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _heading(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    _set_font(p.add_run(f"■ {text}"), size=12, bold=True)


def _para(doc, text: str, *, bullet: bool = False) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    if bullet:
        p.paragraph_format.left_indent = Pt(12)
        p.paragraph_format.first_line_indent = Pt(-10)
        text = f"・{text}"
    _set_font(p.add_run(text), size=10.5)


def _bullets_or_none(doc, items: list[str]) -> None:
    if not items:
        _para(doc, "なし")
        return
    for item in items:
        _para(doc, item, bullet=True)


def _todo_table(doc, todos: list[dict[str, str]]) -> None:
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, label in zip(table.rows[0].cells, ("タスク", "担当者", "期限")):
        _shade(cell, "1F3A5F")
        run = cell.paragraphs[0].add_run(label)
        _set_font(run, size=10, bold=True)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        cell.paragraphs[0].paragraph_format.keep_with_next = True
    _repeat_header(table.rows[0])
    for todo in todos:
        cells = table.add_row().cells
        for cell, value in zip(cells, (todo["task"], todo["assignee"], todo["deadline"])):
            _set_font(cell.paragraphs[0].add_run(value), size=10)
    for row in table.rows:
        for cell, width in zip(row.cells, (Cm(8.5), Cm(3), Cm(4.5))):
            cell.width = width


def _multiline(doc, text: str) -> None:
    """改行を含む文章。「・」で始まる行は箇条書き、【】で始まる行は小見出しにする。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        _para(doc, "なし")
    for line in lines:
        if line.startswith("・"):
            _para(doc, line[1:].strip(), bullet=True)
        elif line.startswith("【"):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.keep_with_next = True
            _set_font(p.add_run(line), size=10.5, bold=True)
        else:
            _para(doc, line)


def info_rows(info: MeetingInfo, t: MinutesTypeDef, data: dict[str, Any]) -> list[tuple[str, str]]:
    """文書冒頭の表。会議記録はタイトル・日時・担当者を（編集後の値で）表示する。"""
    title = data.get("title") or info.meeting_name
    when = data.get("datetime") or format_datetime_ja(info.meeting_datetime)
    rows = [("タイトル" if "title" in data else "会議名", title), ("日時", when)]
    if "assignee" in data:
        rows.append(("担当者", data.get("assignee") or "不明"))
    rows += [
        ("会議ツール", TOOL_LABELS.get(info.meeting_tool, "その他")),
        ("参加者", "、".join(info.participants) if info.participants else "記載なし"),
    ]
    return rows


HEADER_KEYS = {"title", "datetime", "assignee"}


def body_fields(t: MinutesTypeDef) -> list[FieldDef]:
    return [f for f in t.fields if f.key not in HEADER_KEYS]


def build_docx(info: MeetingInfo, t: MinutesTypeDef, data: dict[str, Any]) -> bytes:
    try:
        doc = Document()
        normal = doc.styles["Normal"]
        normal.font.name = FONT_NAME
        normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT_NAME)

        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_font(title.add_run(f"{t.doc_title}（AI自動生成ベース資料）"), size=16, bold=True)

        note = doc.add_paragraph()
        note_run = note.add_run(DISCLAIMER)
        _set_font(note_run, size=9)
        note_run.font.color.rgb = RGBColor(0x55, 0x5F, 0x6D)

        _heading(doc, "基本情報")
        rows = info_rows(info, t, data)
        table = doc.add_table(rows=len(rows), cols=2)
        table.style = "Table Grid"
        for i, (label, value) in enumerate(rows):
            label_cell, value_cell = table.rows[i].cells
            _shade(label_cell, "EEF2F7")
            _set_font(label_cell.paragraphs[0].add_run(label), size=10, bold=True)
            _set_font(value_cell.paragraphs[0].add_run(value), size=10)
            label_cell.width, value_cell.width = Cm(3.2), Cm(12.8)

        for field in body_fields(t):
            _heading(doc, field.label)
            value = data.get(field.key)
            if field.kind == "text":
                _multiline(doc, value or "")
            elif field.kind == "list":
                _bullets_or_none(doc, value or [])
            elif value:
                _todo_table(doc, value)
            else:
                _para(doc, "なし")

        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()
    except Exception as exc:
        raise DocxBuildError("Wordファイルの生成に失敗しました。") from exc
