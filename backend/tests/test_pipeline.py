import json
from unittest.mock import patch

from app.services.crypto import encrypt_token
from app.services.pipeline import PipelineDeps, run_pipeline
from tests.conftest import SAMPLE_DIR, FakeAnalyzer, FakeTranscriber

MID = "11111111-1111-1111-1111-111111111111"


def _deps(repo, settings):
    return PipelineDeps(
        repo=repo, transcriber=FakeTranscriber(), analyzer=FakeAnalyzer(), settings=settings
    )


def test_text_input_runs_to_generated_without_dropbox(repo, settings):
    repo.add_meeting(MID)
    repo.storage[("uploads", f"user-a/{MID}/source.txt")] = (SAMPLE_DIR / "eigyo_teirei_2026-10-08.txt").read_bytes()
    run_pipeline(_deps(repo, settings), MID)

    m = repo.meetings[MID]
    assert m["status"] == "GENERATED", m["error_message"]
    assert repo.status_history == ["TRANSCRIBING", "TRANSCRIBED", "ANALYZING", "GENERATING", "GENERATING", "GENERATED", "GENERATED"]
    assert ("uploads", f"user-a/{MID}/source.txt") not in repo.storage  # 元ファイルは削除
    assert {f["file_type"] for f in repo.list_files(MID)} == {"transcript", "docx", "pdf"}
    data = repo.minutes[MID]["data"]
    # タイトル・日時は AI ではなく会議情報から入る
    assert data["title"] == "営業部 定例会議" and data["datetime"] == "2026/10/08 10:00"
    assert data["assignee"] == "山田" and "【TODO（担当者・期限）】" in data["details"]


def test_each_minutes_type_is_sent_to_ai(repo, settings):
    for i, type_key in enumerate(["review", "daily"]):
        mid = f"{MID[:-1]}{i}"
        repo.add_meeting(mid, minutes_type=type_key, source_file_path=f"user-a/{mid}/source.txt")
        repo.storage[("uploads", f"user-a/{mid}/source.txt")] = "鈴木：振り返りを始めます。".encode()
        deps = _deps(repo, settings)
        run_pipeline(deps, mid)
        assert repo.meetings[mid]["status"] == "GENERATED", repo.meetings[mid]["error_message"]
        assert deps.analyzer.calls[0]["minutes_type"] == type_key
        assert repo.minutes[mid]["minutes_type"] == type_key
    assert repo.minutes[f"{MID[:-1]}0"]["data"]["action_items"][0]["assignee"] == "高橋"
    assert "title" not in repo.minutes[f"{MID[:-1]}1"]["data"]


def test_failure_records_step_and_retry_resumes_there(repo, settings):
    repo.add_meeting(MID)
    repo.storage[("uploads", f"user-a/{MID}/source.txt")] = "山田：A案で進めましょう。".encode()
    deps = _deps(repo, settings)
    deps.analyzer.content = "壊れたJSON"
    run_pipeline(deps, MID)
    m = repo.meetings[MID]
    assert (m["status"], m["error_step"]) == ("ERROR", "analyze")
    assert m["error_message"] == "AIの出力形式が正しくありませんでした。再試行してください。"

    deps.analyzer.content = None
    run_pipeline(deps, MID)  # 文字起こしはやり直さない（元ファイルはもう無い）
    assert repo.meetings[MID]["status"] == "GENERATED"


def test_missing_api_key_is_reported(repo, settings):
    repo.add_meeting(MID, status="TRANSCRIBED")
    repo.transcripts[MID] = "山田：テスト"
    deps = _deps(repo, settings)
    deps.analyzer.problem = "Gemini APIキーが設定されていないため、AI解析を実行できません。"
    run_pipeline(deps, MID)
    assert (repo.meetings[MID]["error_step"], repo.meetings[MID]["error_message"]) == ("analyze", deps.analyzer.problem)


def test_audio_input_is_transcribed_with_participant_names(repo, settings):
    repo.add_meeting(MID, input_type="audio", source_file_name="会議.webm", source_file_path=f"user-a/{MID}/source.webm")
    repo.storage[("uploads", f"user-a/{MID}/source.webm")] = b"audio-bytes"
    deps = _deps(repo, settings)
    deps.transcriber.transcript = "山田：A案で進めましょう。"
    run_pipeline(deps, MID)
    assert repo.meetings[MID]["status"] == "GENERATED", repo.meetings[MID]["error_message"]
    assert deps.transcriber.calls[0]["participants"] == ["山田", "佐藤"]
    assert deps.transcriber.calls[0]["source"].suffix == ".webm"
    assert repo.transcripts[MID] == "山田：A案で進めましょう。"
    assert repo.minutes[MID]["ai_model"] == "fake-model"


def test_dropbox_step_uploads_and_completes(repo, settings):
    from cryptography.fernet import Fernet

    settings.token_encryption_key = Fernet.generate_key().decode()
    settings.dropbox_app_key, settings.dropbox_app_secret = "key", "secret"
    repo.add_meeting(MID, status="TRANSCRIBED")
    repo.transcripts[MID] = "山田：テスト"
    repo.save_file(MID, "transcript", "transcript.txt", f"user-a/{MID}/transcript.txt")
    repo.storage[("outputs", f"user-a/{MID}/transcript.txt")] = "山田：テスト".encode()
    repo.dropbox["user-a"] = {"refresh_token_encrypted": encrypt_token("rt", settings.token_encryption_key)}

    captured = {}

    def fake_upload(app_key, app_secret, refresh_token, folder, files, *, reuse_folder):
        captured.update(folder=folder, names=[f.name for f in files], token=refresh_token, reuse=reuse_folder)
        return folder, {f.name: f"{folder}/{f.name}" for f in files}

    with patch("app.services.pipeline.upload_files", fake_upload):
        run_pipeline(_deps(repo, settings), MID)

    m = repo.meetings[MID]
    assert m["status"] == "COMPLETED", m["error_message"]
    assert captured == {
        "folder": "/AI議事録/2026/10月/2026-10-08_営業部 定例会議",
        "names": ["transcript.txt", "meeting_minutes.docx", "meeting_minutes.pdf"],
        "token": "rt",
        "reuse": False,
    }
    assert m["dropbox_folder_path"] == captured["folder"]
    assert repo.files[(MID, "pdf")]["dropbox_path"].endswith("meeting_minutes.pdf")
