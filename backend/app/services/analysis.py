"""文字起こしから議事録の構造化データを生成する。

標準は Google Gemini API（無料枠あり）。外部に送れない場合は、社内 PC などで動かす
Ollama（ローカル LLM）に切り替えられる。どちらも JSON スキーマを指定して構造化出力させる。
"""

import json
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

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


class Analyzer(Protocol):
    model_name: str

    def check(self) -> str | None:
        """設定に問題があれば、画面に表示するメッセージを返す。"""

    def analyze(self, info: MeetingInfo, transcript: str) -> MinutesData: ...


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


def _parse_minutes(content: str) -> MinutesData:
    try:
        data = MinutesData.model_validate_json(content)
    except ValueError as exc:
        raise AnalysisError("AIの出力形式が正しくありませんでした。再試行してください。") from exc
    return normalize_minutes(data)


def _without_additional_properties(schema: Any) -> Any:
    """Gemini の構造化出力が受け付けないキーワードを取り除く。"""
    if isinstance(schema, dict):
        return {k: _without_additional_properties(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_without_additional_properties(v) for v in schema]
    return schema


GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRY_STATUSES = {429, 500, 503}
RETRY_WAITS = (5, 20)


class GeminiAnalyzer:
    """Google Gemini API（REST）で解析する。

    注意：無料枠では、送った内容が Google のサービス改善に使われることがある。機密の会議には有料枠を使うこと。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.model_name = model
        self.http = http or httpx.Client(timeout=600)
        self.sleep = sleep

    def check(self) -> str | None:
        if not self.api_key:
            return "Gemini APIキーが設定されていないため、AI解析を実行できません。"
        return None

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        url = GEMINI_ENDPOINT.format(model=self.model_name)
        for attempt in range(len(RETRY_WAITS) + 1):
            try:
                response = self.http.post(url, json=body, headers={"x-goog-api-key": self.api_key})
            except httpx.HTTPError as exc:
                if attempt == len(RETRY_WAITS):
                    raise AnalysisError("AI APIに接続できませんでした。時間をおいて再試行してください。") from exc
                self.sleep(RETRY_WAITS[attempt])
                continue
            if response.status_code in RETRY_STATUSES and attempt < len(RETRY_WAITS):
                self.sleep(RETRY_WAITS[attempt])
                continue
            return response
        raise AssertionError("unreachable")

    def analyze(self, info: MeetingInfo, transcript: str) -> MinutesData:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": build_user_message(info, transcript)}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseJsonSchema": _without_additional_properties(MINUTES_JSON_SCHEMA),
            },
        }
        response = self._post(body)
        if response.status_code == 429:
            raise AnalysisError("Gemini APIの無料枠の利用上限に達しました。しばらく時間をおいて再試行してください。")
        if response.status_code in (400, 401, 403) and "API_KEY" in response.text:
            raise AnalysisError("Gemini APIキーが正しくありません。サーバーの設定を確認してください。")
        if response.status_code >= 400:
            raise AnalysisError("AI APIの呼び出しに失敗しました。時間をおいて再試行してください。")

        payload = response.json()
        if payload.get("promptFeedback", {}).get("blockReason"):
            raise AnalysisError("AIが処理を拒否しました。文字起こしの内容を確認してください。")
        candidates = payload.get("candidates") or []
        if not candidates:
            raise AnalysisError("AIから結果が返りませんでした。再試行してください。")
        candidate = candidates[0]
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise AnalysisError("AIの出力が長すぎて途中で終了しました。")
        if candidate.get("finishReason") not in (None, "STOP"):
            raise AnalysisError("AIが処理を拒否しました。文字起こしの内容を確認してください。")
        parts = candidate.get("content", {}).get("parts") or []
        # 思考モデルは思考の要約を thought=True のパートで返すことがあるので除く
        content = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return _parse_minutes(content)


class OllamaAnalyzer:
    """Ollama（社内 PC などで動かすローカル LLM）で解析する。外部にデータを送らないが、
    GPU のない PC では時間がかかり、要約の精度も Gemini より下がる。"""

    def __init__(self, base_url: str, model: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.http = http or httpx.Client(timeout=3600)

    def check(self) -> str | None:
        if not self.base_url or not self.model_name:
            return "ローカルAI（Ollama）の設定がないため、AI解析を実行できません。"
        return None

    def analyze(self, info: MeetingInfo, transcript: str) -> MinutesData:
        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(info, transcript)},
            ],
            "format": MINUTES_JSON_SCHEMA,
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 32768},
        }
        try:
            response = self.http.post(f"{self.base_url}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise AnalysisError("ローカルAI（Ollama）に接続できませんでした。起動しているか確認してください。") from exc
        if response.status_code >= 400:
            raise AnalysisError("ローカルAI（Ollama）の呼び出しに失敗しました。モデル名を確認してください。")
        payload = response.json()
        if payload.get("done_reason") == "length":
            raise AnalysisError("AIの出力が長すぎて途中で終了しました。")
        return _parse_minutes(payload.get("message", {}).get("content", ""))
