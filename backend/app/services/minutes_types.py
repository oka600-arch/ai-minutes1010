"""議事録の種類（会議記録・会議の振り返り・日常の振り返り）と、それぞれの項目の定義。

AI への指示（プロンプト・JSON スキーマ）、画面の表示と編集、Word/PDF の生成は、すべてこの定義から作る。
項目を増やすときはここだけを変更すればよい。
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.schemas import NOT_SPECIFIED, UNKNOWN, MeetingInfo
from app.services.naming import format_datetime_ja

FieldKind = Literal["text", "list", "todos"]
MinutesTypeKey = Literal["record", "review", "daily"]


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: FieldKind
    # AI への指示。None の項目は AI に作らせず、会議情報から埋める（タイトル・日時）
    hint: str | None = None


@dataclass(frozen=True)
class MinutesTypeDef:
    key: MinutesTypeKey
    label: str
    description: str
    doc_title: str
    purpose: str  # AI に伝える「何をまとめる資料か」
    fields: tuple[FieldDef, ...]

    def ai_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.hint is not None]


TODO_HINT = (
    "発言から抽出したタスク。task（タスク内容）、assignee（担当者）、deadline（期限）。"
    f"担当者が特定できなければ「{UNKNOWN}」、期限が明示されていなければ「{NOT_SPECIFIED}」とする。"
)

MINUTES_TYPES: dict[str, MinutesTypeDef] = {
    "record": MinutesTypeDef(
        key="record",
        label="会議記録",
        description="タイトル・日時・担当者・内容・要約文・詳細をまとめます。生成後に画面で書き換えられます。",
        doc_title="会議記録",
        purpose="会議の内容を記録として残すための議事録",
        fields=(
            FieldDef("title", "タイトル", "text"),
            FieldDef("datetime", "日時", "text"),
            FieldDef(
                "assignee", "担当者", "text",
                f"会議の進行役・取りまとめ役など、この会議の担当者。発言から特定できなければ「{UNKNOWN}」とする。",
            ),
            FieldDef("content", "内容", "list", "会議で話し合った議題・内容を、1項目1行の箇条書きで簡潔に。"),
            FieldDef("summary", "要約文", "text", "会議全体の要約を2〜4文で。"),
            FieldDef(
                "details", "詳細", "text",
                "議題ごとの詳しい内容。次の見出しを使い、該当がなければ見出しごと省略する。"
                "【議論の内容】【決定事項】【TODO（担当者・期限）】【未決事項】【次回確認事項】。"
                "見出しの下は「・」で始まる箇条書きにする。"
                f"TODO は「・タスク（担当：〇〇／期限：〇〇）」の形で、担当者が不明なら「{UNKNOWN}」、"
                f"期限が不明なら「{NOT_SPECIFIED}」と書く。",
            ),
        ),
    ),
    "review": MinutesTypeDef(
        key="review",
        label="会議の振り返り",
        description="会議で話された問題について、原因・改善点などを整理します。",
        doc_title="会議の振り返りまとめ",
        purpose="会議で話された問題や結果について、原因と改善策を整理する振り返り資料",
        fields=(
            FieldDef("summary", "概要", "text", "振り返りの対象と結論を2〜4文で。"),
            FieldDef("good_points", "良かった点", "list", "うまくいったこと・続けるべきこと。"),
            FieldDef("issues", "課題・問題点", "list", "起きた問題、うまくいかなかったこと。"),
            FieldDef(
                "causes", "原因", "list",
                "課題・問題点の原因。発言で述べられた原因だけを書き、推測で原因を作らない。どの課題の原因か分かるように書く。",
            ),
            FieldDef("improvements", "改善策", "list", "今後の改善策・再発防止策として話された内容。"),
            FieldDef("action_items", "今後のアクション", "todos", TODO_HINT),
        ),
    ),
    "daily": MinutesTypeDef(
        key="daily",
        label="日常の振り返り",
        description="日々の振り返りの会話から、出来事・気づき・次にやることをまとめます。",
        doc_title="日常の振り返りまとめ",
        purpose="日々の業務や出来事を振り返る会話（朝会・夕会・1on1 など）のまとめ",
        fields=(
            FieldDef("summary", "概要", "text", "振り返りの内容を2〜3文で。"),
            FieldDef("activities", "出来事・取り組んだこと", "list", "話の中で出てきた出来事や取り組んだこと。誰の話か分かれば名前を添える。"),
            FieldDef("good_points", "良かったこと", "list", "うまくいったこと、嬉しかったこと。"),
            FieldDef("learnings", "気づき・学び", "list", "気づいたこと、学んだこと。"),
            FieldDef("concerns", "困りごと・課題", "list", "困っていること、うまくいかなかったこと、相談事項。"),
            FieldDef("next_actions", "次にやること", "list", "次に取り組むと話されたこと。誰がやるか分かれば名前を添える。"),
        ),
    ),
}

DEFAULT_TYPE = "record"


class MinutesDataError(ValueError):
    pass


def get_type(key: str | None) -> MinutesTypeDef:
    return MINUTES_TYPES.get(key or DEFAULT_TYPE, MINUTES_TYPES[DEFAULT_TYPE])


# ---------------------------------------------------------------- AI 用


def json_schema(t: MinutesTypeDef) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for f in t.ai_fields():
        if f.kind == "text":
            props[f.key] = {"type": "string"}
        elif f.kind == "list":
            props[f.key] = {"type": "array", "items": {"type": "string"}}
        else:
            props[f.key] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["task", "assignee", "deadline"],
                    "properties": {k: {"type": "string"} for k in ("task", "assignee", "deadline")},
                },
            }
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def field_instructions(t: MinutesTypeDef) -> str:
    return "\n".join(f"- {f.key}（{f.label}）: {f.hint}" for f in t.ai_fields())


# ---------------------------------------------------------------- 検証・整形


def _text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MinutesDataError("文字列であるべき項目に、別の形式の値が入っています。")
    return value.strip()


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MinutesDataError("箇条書きの項目の形式が正しくありません。")
    return [s for s in (_text(v) for v in value) if s]


def _todos(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise MinutesDataError("TODO の形式が正しくありません。")
    todos = []
    for v in value:
        task = _text(v.get("task"))
        if not task:
            continue
        todos.append({
            "task": task,
            "assignee": _text(v.get("assignee")) or UNKNOWN,
            "deadline": _text(v.get("deadline")) or NOT_SPECIFIED,
        })
    return todos


def normalize(t: MinutesTypeDef, data: dict[str, Any], *, ai_only: bool = False) -> dict[str, Any]:
    """AI の出力やユーザーの編集内容を、種類の定義どおりの形に整える。知らない項目は捨てる。"""
    if not isinstance(data, dict):
        raise MinutesDataError("議事録データの形式が正しくありません。")
    out: dict[str, Any] = {}
    for f in t.ai_fields() if ai_only else t.fields:
        raw = data.get(f.key)
        out[f.key] = _text(raw) if f.kind == "text" else _list(raw) if f.kind == "list" else _todos(raw)
    if out.get("assignee") == "":
        out["assignee"] = UNKNOWN
    return out


def fill_meeting_info(t: MinutesTypeDef, data: dict[str, Any], info: MeetingInfo) -> dict[str, Any]:
    """AI に作らせない項目（タイトル・日時）を会議情報から埋める。"""
    keys = {f.key for f in t.fields}
    filled = dict(data)
    if "title" in keys:
        filled["title"] = info.meeting_name
    if "datetime" in keys:
        filled["datetime"] = format_datetime_ja(info.meeting_datetime)
    return {f.key: filled.get(f.key, "" if f.kind == "text" else []) for f in t.fields}


def describe_types() -> list[dict[str, Any]]:
    """画面用の定義（API で返す）。"""
    return [
        {
            "key": t.key,
            "label": t.label,
            "description": t.description,
            "fields": [{"key": f.key, "label": f.label, "kind": f.kind} for f in t.fields],
        }
        for t in MINUTES_TYPES.values()
    ]
