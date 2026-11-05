import json
from datetime import datetime

import httpx
import pytest

from app.schemas import NOT_SPECIFIED, UNKNOWN, MeetingInfo
from app.services.analysis import AnalysisError, GeminiAnalyzer, OllamaAnalyzer, build_user_message, system_prompt
from app.services.minutes_types import MINUTES_TYPES

INFO = MeetingInfo(meeting_name="営業部 定例会議", meeting_datetime=datetime(2026, 10, 8, 10), participants=["山田", "佐藤"])
REVIEW = MINUTES_TYPES["review"]
RECORD = MINUTES_TYPES["record"]
EMPTY = json.dumps({"summary": "", "good_points": [], "issues": [], "causes": [], "improvements": [], "action_items": []})


def _gemini_reply(text: str, finish: str = "STOP") -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]}


def _gemini(responses: list[httpx.Response], requests: list[httpx.Request] | None = None) -> GeminiAnalyzer:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return queue.pop(0)

    return GeminiAnalyzer("test-key", "gemini-2.5-flash", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None)


def test_user_message_follows_input_format():
    payload = json.loads(build_user_message(INFO, "山田：こんにちは").split("\n\n", 1)[1])
    assert payload == {"meeting_name": "営業部 定例会議", "meeting_date": "2026-10-08", "participants": ["山田", "佐藤"], "transcript": "山田：こんにちは"}


def test_gemini_request_and_blank_values_become_unknown():
    content = json.dumps({
        "summary": " 概要 ", "good_points": [], "issues": ["告知が遅れた", " "], "causes": [], "improvements": [],
        "action_items": [{"task": "資料作成", "assignee": "", "deadline": " "}, {"task": "", "assignee": "山田", "deadline": "10/15"}],
        "extra": "知らない項目は捨てる",
    }, ensure_ascii=False)
    requests: list[httpx.Request] = []
    result = _gemini([httpx.Response(200, json=_gemini_reply(content))], requests).analyze(INFO, "山田：資料作成をお願いします", REVIEW)
    assert result["summary"] == "概要"
    assert result["issues"] == ["告知が遅れた"]
    assert "extra" not in result
    assert result["action_items"] == [{"task": "資料作成", "assignee": UNKNOWN, "deadline": NOT_SPECIFIED}]

    req = requests[0]
    assert req.url.path.endswith("/models/gemini-2.5-flash:generateContent")
    assert req.headers["x-goog-api-key"] == "test-key"  # キーは URL ではなくヘッダーで送る
    body = json.loads(req.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "additionalProperties" not in json.dumps(body["generationConfig"]["responseJsonSchema"])
    prompt = body["systemInstruction"]["parts"][0]["text"]
    assert "創作の禁止" in prompt and "causes（原因）" in prompt
    assert body["generationConfig"]["responseJsonSchema"]["required"] == ["summary", "good_points", "issues", "causes", "improvements", "action_items"]


def test_record_prompt_does_not_ask_ai_for_title_or_datetime():
    prompt = system_prompt(RECORD)
    assert "assignee（担当者）" in prompt and "details（詳細）" in prompt
    assert "title（" not in prompt and "datetime（" not in prompt


def test_gemini_retries_rate_limit_then_reports_quota():
    ok = _gemini([httpx.Response(429), httpx.Response(200, json=_gemini_reply(EMPTY))])
    assert ok.analyze(INFO, "x", REVIEW)["summary"] == ""
    with pytest.raises(AnalysisError, match="無料枠"):
        _gemini([httpx.Response(429)] * 3).analyze(INFO, "x", REVIEW)


def test_gemini_bad_key_and_missing_key():
    bad = httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}})
    with pytest.raises(AnalysisError, match="APIキーが正しくありません"):
        _gemini([bad]).analyze(INFO, "x", REVIEW)
    assert "APIキー" in (GeminiAnalyzer("").check() or "")


def test_gemini_truncated_blocked_or_broken_output_raises():
    with pytest.raises(AnalysisError, match="長すぎ"):
        _gemini([httpx.Response(200, json=_gemini_reply("{", "MAX_TOKENS"))]).analyze(INFO, "x", REVIEW)
    with pytest.raises(AnalysisError, match="拒否"):
        _gemini([httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})]).analyze(INFO, "x", REVIEW)
    with pytest.raises(AnalysisError, match="形式"):
        _gemini([httpx.Response(200, json=_gemini_reply("壊れたJSON"))]).analyze(INFO, "x", REVIEW)


def test_gemini_ignores_thought_parts():
    reply = {"candidates": [{"content": {"parts": [{"text": "考え中…", "thought": True}, {"text": EMPTY}]}, "finishReason": "STOP"}]}
    assert _gemini([httpx.Response(200, json=reply)]).analyze(INFO, "x", REVIEW)["action_items"] == []


def test_ollama_sends_schema_and_parses_reply():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": EMPTY}, "done_reason": "stop"})

    analyzer = OllamaAnalyzer("http://localhost:11434/", "qwen2.5:7b", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert analyzer.analyze(INFO, "x", REVIEW)["issues"] == []
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == "http://localhost:11434/api/chat"
    assert body["model"] == "qwen2.5:7b" and body["format"]["required"][0] == "summary" and body["stream"] is False


def test_ollama_unreachable_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(AnalysisError, match="接続できません"):
        OllamaAnalyzer("http://localhost:11434", "m", http=httpx.Client(transport=httpx.MockTransport(handler))).analyze(INFO, "x", REVIEW)
