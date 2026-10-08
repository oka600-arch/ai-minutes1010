import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.deps import get_pipeline_deps, get_repo
from app.main import app
from app.services.pipeline import PipelineDeps
from tests.conftest import FakeOpenAI

MID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def client(repo, settings, sample_minutes):
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_pipeline_deps] = lambda: PipelineDeps(
        repo=repo, openai=FakeOpenAI(content=sample_minutes.model_dump_json()), settings=settings
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
    assert minutes["todos"][0]["task"] == "製造業30社へのご案内メール送付"
    url = client.get(f"/api/meetings/{MID}/files/pdf", headers=A).json()
    assert url["file_name"] == "2026-10-08_営業部 定例会議_議事録.pdf"
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
