"""文字起こしから議事録の構造化データを生成する（OpenAI 構造化出力）。"""

import json
from typing import Any, Protocol

from app.schemas import NOT_SPECIFIED, UNKNOWN, MeetingInfo, MinutesData

SYSTEM_PROMPT = f"""あなたは企業の会議の議事録作成を支援するアシスタントです。
会議の文字起こしから、参加者が正式な議事録を作るための「ベース資料」を作成します。
単純な要約ではなく、業務上重要な情報を構造化して抽出してください。

# 整理のルール
- 挨拶、相槌、言い淀み、重複発言、雑談、業務に関係しない会話、同じ内容の繰り返しは削除または簡略化する。
- ただし、業務上重要な背景情報（理由・前提・数字の根拠など）は削除しない。
- 文体は「〜した」「〜する」の常体で、簡潔に書く。

# 各項目
- summary: 会議全体の概要を2〜4文で。
- discussion: 議題ごとに topic（議題名）と content（議論の要点。複数ある場合は「・」で始まる行を改行区切り）。
- decisions: 会議中に合意・決定された事項。「A案で進めましょう」→「A案を採用する」のように決定事項の形に言い換える。
- todos: 発言から抽出したタスク。task（タスク内容）、assignee（担当者）、deadline（期限）。
- unresolved_items: 結論が出なかった事項、持ち越し・確認待ちの事項。
- next_actions: 次回会議で確認すべき事項（次回日程が決まった場合はそれも含める）。

# 最重要：創作の禁止
- 文字起こしから確認できない情報を作ってはいけない。特に担当者・期限・決定事項・数字・金額・日付。
- 担当者が特定できない場合、assignee は「{UNKNOWN}」とする。
- 期限が明示されていない場合、deadline は「{NOT_SPECIFIED}」とする。
- 「来週まで」「月末」など相対的な期限は、日付に変換せず発言どおりに書く。
- 結論が出ていないものを decisions に入れない（unresolved_items に入れる）。
- 該当する項目がない場合は空の配列にする。
"""

MINUTES_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "discussion", "decisions", "todos", "unresolved_items", "next_actions"],
    "properties": {
        "summary": {"type": "string"},
        "discussion": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["topic", "content"],
                "properties": {"topic": {"type": "string"}, "content": {"type": "string"}},
            },
        },
        "decisions": {"type": "array", "items": {"type": "string"}},
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["task", "assignee", "deadline"],
                "properties": {
                    "task": {"type": "string"},
                    "assignee": {"type": "string"},
                    "deadline": {"type": "string"},
                },
            },
        },
        "unresolved_items": {"type": "array", "items": {"type": "string"}},
        "next_actions": {"type": "array", "items": {"type": "string"}},
    },
}


class AnalysisError(Exception):
    pass


class ChatClient(Protocol):
    """OpenAI クライアントのうち、ここで使う部分だけを表す（テストで差し替えるため）。"""

    chat: Any


def build_user_message(info: MeetingInfo, transcript: str) -> str:
    payload = {
        "meeting_name": info.meeting_name,
        "meeting_date": info.meeting_datetime.date().isoformat(),
        "participants": info.participants,
        "transcript": transcript,
    }
    return (
        "以下の会議データから議事録のベース資料を作成してください。\n"
        "meeting_date は会議の開催日です（相対的な期限を日付に変換するためには使わないこと）。\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _clean(value: str, fallback: str) -> str:
    value = value.strip()
    return value if value else fallback


def normalize_minutes(data: MinutesData) -> MinutesData:
    """AI の出力を整える。空欄の担当者・期限は所定の文言に置き換える。"""
    for todo in data.todos:
        todo.task = todo.task.strip()
        todo.assignee = _clean(todo.assignee, UNKNOWN)
        todo.deadline = _clean(todo.deadline, NOT_SPECIFIED)
    data.todos = [t for t in data.todos if t.task]
    data.decisions = [d.strip() for d in data.decisions if d.strip()]
    data.unresolved_items = [u.strip() for u in data.unresolved_items if u.strip()]
    data.next_actions = [n.strip() for n in data.next_actions if n.strip()]
    data.discussion = [d for d in data.discussion if d.topic.strip() or d.content.strip()]
    data.summary = data.summary.strip()
    return data


def _sampling_params(model: str) -> dict[str, Any]:
    # 推論系モデル（o シリーズ・gpt-5 系）は temperature を受け付けない
    if model.startswith(("o1", "o3", "o4", "gpt-5")):
        return {}
    return {"temperature": 0.2}


def analyze_transcript(client: ChatClient, model: str, info: MeetingInfo, transcript: str) -> MinutesData:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(info, transcript)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "meeting_minutes", "strict": True, "schema": MINUTES_JSON_SCHEMA},
            },
            **_sampling_params(model),
        )
    except Exception as exc:  # OpenAI SDK の各種例外
        raise AnalysisError("AI APIの呼び出しに失敗しました。") from exc

    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise AnalysisError("AIが処理を拒否しました。文字起こしの内容を確認してください。")
    if choice.finish_reason == "length":
        raise AnalysisError("AIの出力が長すぎて途中で終了しました。")
    try:
        data = MinutesData.model_validate_json(choice.message.content or "")
    except ValueError as exc:
        raise AnalysisError("AIの出力形式が正しくありませんでした。") from exc
    return normalize_minutes(data)
