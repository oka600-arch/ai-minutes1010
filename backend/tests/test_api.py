import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.deps import get_pipeline_deps, get_repo
from app.main import app
from app.services.pipeline import PipelineDeps
from tests.conftest import FakeAnalyzer, FakeTranscriber

MID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def client(repo, settings):
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        repo=repo,
        transcriber=FakeTranscriber(),
        analyzer=FakeAnalyzer(),
        settings=settings,
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}
BODY = {
    "meeting_name": "営業部 定例会議", "meeting_datetime": "2026-10-08T10:00:00+09:00", "meeting_tool": "zoom",
    "participants": ["山田", "佐藤", "田中"], "input_type": "text", "file_name": "会議.vtt", "file_size": 2048,
}


def test_login_required(client):
    assert client.get("/api/meetings").status_code == 401
    assert client.get("/api/meetings", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_create_meeting_returns_upload_target(client, repo):
    res = client.post("/api/meetings", json=BODY, headers=A)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["upload_token"] == "upload-token"
    assert data["upload_path"].startswith("user-a/") and data["upload_path"].endswith("/source.vtt")
    assert [p["name"] for p in data["meeting"]["participants"]] == ["山田", "佐藤", "田中"]


@pytest.mark.parametrize("patch,code", [
    ({"file_name": "a.pdf"}, 400),
    ({"input_type": "audio", "file_name": "a.txt"}, 400),
    ({"file_size": 6 * 1024 * 1024}, 413),
    ({"input_type": "audio", "file_name": "a.mp3", "file_size": 101 * 1024 * 1024}, 413),
    ({"meeting_name": ""}, 422),
])
def test_invalid_uploads_are_rejected(client, patch, code):
    assert client.post("/api/meetings", json={**BODY, **patch}, headers=A).status_code == code


def test_other_users_meeting_is_not_visible(client, repo):
    repo.add_meeting(MID, user_id="user-a")
    assert client.get(f"/api/meetings/{MID}", headers=A).status_code == 200
    assert client.get(f"/api/meetings/{MID}", headers=B).status_code == 404
    assert client.post(f"/api/meetings/{MID}/process", headers=B).status_code == 404
    assert client.get("/api/meetings", headers=B).json() == []


def test_process_runs_pipeline_and_minutes_are_returned(client, repo):
    repo.add_meeting(MID)
    repo.storage[("uploads", f"user-a/{MID}/source.txt")] = "山田：A案で進めましょう。".encode()
    res = client.post(f"/api/meetings/{MID}/process", headers=A)
    assert res.status_code == 202
    # TestClient はバックグラウンドタスクをレスポンス後に同期実行する
    assert client.get(f"/api/meetings/{MID}", headers=A).json()["status"] == "GENERATED"
    minutes = client.get(f"/api/meetings/{MID}/minutes", headers=A).json()
    assert minutes["minutes_type"] == "record"
    assert minutes["data"]["title"] == "営業部 定例会議" and minutes["data"]["assignee"] == "山田"
    url = client.get(f"/api/meetings/{MID}/files/pdf", headers=A).json()
    assert url["file_name"] == "2026-10-08_営業部 定例会議_会議記録.pdf"
    # 完了後に再度 process を呼ぶと 409
    assert client.post(f"/api/meetings/{MID}/process", headers=A).status_code == 409


def test_dropbox_save_requires_connection(client, repo):
    repo.add_meeting(MID, status="GENERATED")
    res = client.post(f"/api/meetings/{MID}/dropbox", headers=A)
    assert res.status_code == 400
    assert "連携されていません" in res.json()["detail"]


def test_dropbox_status_and_unconfigured_connect(client):
    assert client.get("/api/dropbox/status", headers=A).json() == {"connected": False, "email": None, "configured": False}
    assert client.get("/api/dropbox/connect", headers=A).status_code == 503


def test_dropbox_callback_with_unknown_state_redirects(client, repo):
    repo.pop_oauth_state = lambda state: None
    res = client.get("/api/dropbox/callback?state=x&code=y", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].endswith("/settings?dropbox=expired")


def test_minutes_types_are_listed(client):
    types = client.get("/api/minutes-types").json()
    assert [t["key"] for t in types] == ["record", "review", "daily"]
    record = types[0]
    assert [f["label"] for f in record["fields"]] == ["タイトル", "日時", "担当者", "内容", "要約文", "詳細"]


def test_create_meeting_keeps_minutes_type(client, repo):
    res = client.post("/api/meetings", json={**BODY, "minutes_type": "review"}, headers=A)
    assert res.status_code == 201
    assert res.json()["meeting"]["minutes_type"] == "review"
    assert client.post("/api/meetings", json={**BODY, "minutes_type": "unknown"}, headers=A).status_code == 422


def _generated(client, repo, minutes_type="record"):
    repo.add_meeting(MID, minutes_type=minutes_type)
    repo.storage[("uploads", f"user-a/{MID}/source.txt")] = "山田：A案で進めましょう。".encode()
    client.post(f"/api/meetings/{MID}/process", headers=A)
    return client.get(f"/api/meetings/{MID}/minutes", headers=A).json()["data"]


def test_edit_minutes_saves_and_regenerates_documents(client, repo):
    data = _generated(client, repo)
    before = repo.storage[("outputs", f"user-a/{MID}/meeting_minutes.docx")]
    data["title"] = "営業部 定例会議（修正版）"
    data["content"] = ["来月の営業目標", "  ", "新規顧客へのアプローチ"]
    res = client.put(f"/api/meetings/{MID}/minutes", json={"data": data}, headers=A)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["data"]["title"] == "営業部 定例会議（修正版）"
    assert body["data"]["content"] == ["来月の営業目標", "新規顧客へのアプローチ"]  # 空行は除く
    assert body["edited_at"] is not None
    assert repo.storage[("outputs", f"user-a/{MID}/meeting_minutes.docx")] != before


def test_edit_minutes_rejects_bad_data_and_other_users(client, repo):
    data = _generated(client, repo)
    assert client.put(f"/api/meetings/{MID}/minutes", json={"data": {**data, "content": "文字列"}}, headers=A).status_code == 422
    assert client.put(f"/api/meetings/{MID}/minutes", json={"data": data}, headers=B).status_code == 404


def test_edit_is_blocked_while_processing(client, repo):
    _generated(client, repo)
    repo.meetings[MID]["status"] = "ANALYZING"
    res = client.put(f"/api/meetings/{MID}/minutes", json={"data": {}}, headers=A)
    assert res.status_code == 409


def test_edit_resaves_to_dropbox_when_already_saved(client, repo, monkeypatch):
    data = _generated(client, repo)
    repo.meetings[MID].update(status="COMPLETED", dropbox_folder_path="/AI議事録/2026/10月/2026-10-08_営業部 定例会議")
    repo.dropbox["user-a"] = {"refresh_token_encrypted": "x"}
    calls = []
    monkeypatch.setattr("app.routers.meetings.run_pipeline", lambda deps, mid, only=None: calls.append((mid, only)))
    assert client.put(f"/api/meetings/{MID}/minutes", json={"data": data}, headers=A).status_code == 200
    assert calls == [(MID, "dropbox")]
