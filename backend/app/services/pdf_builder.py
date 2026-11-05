"""議事録の PDF ファイルを生成する。日本語は Noto Sans JP を埋め込んで文字化けを防ぐ。"""

from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas import MeetingInfo
from app.services.docx_builder import DISCLAIMER, body_fields, info_rows
from app.services.minutes_types import MinutesTypeDef

FONT_DIR = Path(__file__).resolve().parents[2] / "fonts"
NAVY = colors.HexColor("#1F3A5F")
LIGHT = colors.HexColor("#EEF2F7")
GRID = colors.HexColor("#C5CDD8")
MUTED = colors.HexColor("#555F6D")


class PdfBuildError(Exception):
    pass


@lru_cache
def _styles() -> dict[str, ParagraphStyle]:
    pdfmetrics.registerFont(TTFont("NotoSansJP", str(FONT_DIR / "NotoSansJP-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("NotoSansJP-Bold", str(FONT_DIR / "NotoSansJP-Bold.ttf")))
    base = dict(fontName="NotoSansJP", fontSize=10, leading=15, wordWrap="CJK")
    return {
        "title": ParagraphStyle("title", **{**base, "fontName": "NotoSansJP-Bold", "fontSize": 16, "leading": 22, "alignment": 1}),
        "note": ParagraphStyle("note", **{**base, "fontSize": 8, "leading": 11, "textColor": MUTED, "alignment": 1}),
        "h": ParagraphStyle("h", **{**base, "fontName": "NotoSansJP-Bold", "fontSize": 12, "leading": 17, "spaceBefore": 10, "spaceAfter": 4, "textColor": NAVY}),
        "topic": ParagraphStyle("topic", **{**base, "fontName": "NotoSansJP-Bold", "spaceBefore": 4}),
        "body": ParagraphStyle("body", **base),
        "bullet": ParagraphStyle("bullet", **{**base, "leftIndent": 12, "firstLineIndent": -10}),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 9.5, "leading": 13}),
        "cell_head": ParagraphStyle("cell_head", **{**base, "fontName": "NotoSansJP-Bold", "fontSize": 9.5, "leading": 13, "textColor": colors.white}),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _bullets(items: list[str], s: dict[str, ParagraphStyle]) -> list:
    if not items:
        return [_p("なし", s["body"])]
    return [_p(f"・{item}", s["bullet"]) for item in items]


def _multiline(text: str, s: dict[str, ParagraphStyle]) -> list:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return [_p("なし", s["body"])]
    out = []
    for line in lines:
        if line.startswith("・"):
            out.append(_p(line, s["bullet"]))
        elif line.startswith("【"):
            out.append(_p(line, s["topic"]))
        else:
            out.append(_p(line, s["body"]))
    return out


def _todo_table(todos: list[dict[str, str]], s: dict[str, ParagraphStyle], width: float) -> Table:
    rows = [[_p(h, s["cell_head"]) for h in ("タスク", "担当者", "期限")]]
    rows += [[_p(t["task"], s["cell"]), _p(t["assignee"], s["cell"]), _p(t["deadline"], s["cell"])] for t in todos]
    table = Table(rows, colWidths=[width - 80 * mm, 30 * mm, 50 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def build_pdf(info: MeetingInfo, t: MinutesTypeDef, data: dict[str, Any]) -> bytes:
    try:
        s = _styles()
        width = A4[0] - 36 * mm
        story: list = [
            _p(f"{t.doc_title}（AI自動生成ベース資料）", s["title"]),
            Spacer(1, 3 * mm),
            _p(DISCLAIMER, s["note"]),
            _p("■ 基本情報", s["h"]),
        ]
        info_table = Table(
            [[_p(k, s["cell"]), _p(v, s["cell"])] for k, v in info_rows(info, t, data)],
            colWidths=[28 * mm, width - 28 * mm],
        )
        info_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, GRID),
            ("BACKGROUND", (0, 0), (0, -1), LIGHT),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(info_table)

        for field in body_fields(t):
            story.append(_p(f"■ {field.label}", s["h"]))
            value = data.get(field.key)
            if field.kind == "text":
                story += _multiline(value or "", s)
            elif field.kind == "list":
                story += _bullets(value or [], s)
            elif value:
                story.append(_todo_table(value, s, width))
            else:
                story.append(_p("なし", s["body"]))

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
            title=f"{t.doc_title} {data.get('title') or info.meeting_name}", author="AI議事録システム",
        )
        doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
        return buf.getvalue()
    except Exception as exc:
        raise PdfBuildError("PDFファイルの生成に失敗しました。") from exc


def _page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("NotoSansJP", 8)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(A4[0] / 2, 9 * mm, f"- {doc.page} -")
    canvas.restoreState()
