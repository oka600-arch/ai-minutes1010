import json
from datetime import datetime

import pytest

from app.schemas import NOT_SPECIFIED, UNKNOWN, MeetingInfo
from app.services.analysis import AnalysisError, analyze_transcript, build_user_message
from tests.conftest import FakeOpenAI

INFO = MeetingInfo(meeting_name="営業部 定例会議", meeting_datetime=datetime(2026, 10, 8, 10), participants=["山田", "佐藤"])


def test_user_message_follows_input_format():
    payload = json.loads(build_user_message(INFO, "山田：こんにちは").split("\n\n", 1)[1])
    assert payload == {"meeting_name": "営業部 定例会議", "meeting_date": "2026-10-08", "participants": ["山田", "佐藤"], "transcript": "山田：こんにちは"}


def test_blank_assignee_and_deadline_become_unknown():
    content = json.dumps({
        "summary": " 概要 ", "discussion": [], "decisions": ["A案を採用する", " "],
        "todos": [{"task": "資料作成", "assignee": "", "deadline": " "}, {"task": "", "assignee": "山田", "deadline": "10/15"}],
        "unresolved_items": [], "next_actions": [],
    }, ensure_ascii=False)
    client = FakeOpenAI(content=content)
    result = analyze_transcript(client, "gpt-4.1", INFO, "山田：資料作成をお願いします")
    assert result.summary == "概要"
    assert result.decisions == ["A案を採用する"]
    assert len(result.todos) == 1
    assert result.todos[0].assignee == UNKNOWN and result.todos[0].deadline == NOT_SPECIFIED
    call = client.calls[0]
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["temperature"] == 0.2


def test_reasoning_models_get_no_temperature():
    client = FakeOpenAI(content=json.dumps({"summary": "", "discussion": [], "decisions": [], "todos": [], "unresolved_items": [], "next_actions": []}))
    analyze_transcript(client, "gpt-5-mini", INFO, "x")
    assert "temperature" not in client.calls[0]


def test_truncated_or_broken_output_raises():
    with pytest.raises(AnalysisError):
        analyze_transcript(FakeOpenAI(content="{", finish_reason="stop"), "gpt-4.1", INFO, "x")
    with pytest.raises(AnalysisError):
        analyze_transcript(FakeOpenAI(content="{}", finish_reason="length"), "gpt-4.1", INFO, "x")
