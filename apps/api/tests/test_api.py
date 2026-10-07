import hashlib
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import storage
from app.models import AuditLog, Competition, Settings, Submission, User, now
from conftest import add_account, login, make_zip, upload

PARTICIPANT_PATHS = ["/api/competition", "/api/submissions/me", "/api/leaderboard"]
HIDDEN_FIELDS = ["private_score", "partition", "predictions", "log_tail", "domain_id", "homologous_superfamily"]


def test_registration_is_gone_and_login_uses_issued_id(client, db, participant):
    assert client.post("/api/auth/register", json={"username": "new", "password": "VeryStrongPassword123"}).status_code in {404, 405}
    stored = db.get(User, participant["id"])
    assert stored.password_hash.startswith("$argon2")
    me = client.get("/api/auth/me").json()
    assert me["username"] == "teamlearner" and "password" not in json.dumps(me)
    assert client.get("/api/admin/teams").status_code == 403
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "teamlearner", "password": "WrongPassword123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "nobody", "password": participant["password"]}).status_code == 401
    # IDs are case-insensitive so a typed capital letter does not lock a team out.
    assert client.post("/api/auth/login", json={"username": " TeamLearner ", "password": participant["password"]}).status_code == 200


def test_one_team_id_can_be_signed_in_on_several_devices(client, db, participant):
    # Teams share one issued ID, so a new login must not sign out the members already in.
    first = client.cookies.get("admin_session")
    client.cookies.clear()
    second = login(client, participant)
    assert first and second
    for session in (first, second):
        client.cookies.set("admin_session", session)
        assert client.get("/api/submissions/me").status_code == 200


def test_admin_issues_resets_and_blocks_accounts(client, db, organizer):
    client.cookies.set("admin_session", organizer)
    team = client.post("/api/admin/teams", json={"name": "Folders"})
    assert team.status_code == 201
    assert client.post("/api/admin/teams", json={"name": "Folders"}).status_code == 409
    issued = client.post("/api/admin/users", json={"team_id": team.json()["id"]}).json()
    assert len(issued["username"]) == 10 and len(issued["temporary_password"]) >= 12
    second = client.post("/api/admin/users", json={"team_id": team.json()["id"], "username": "folders-2"}).json()
    assert second["team_name"] == "Folders"
    assert client.post("/api/admin/users", json={"team_id": team.json()["id"], "username": "folders-2"}).status_code == 409
    listed = next(t for t in client.get("/api/admin/teams").json() if t["name"] == "Folders")
    assert [u["username"] for u in listed["users"]] == [issued["username"], "folders-2"]
    assert "temporary_password" not in json.dumps(listed) and "password_hash" not in json.dumps(listed)

    client.cookies.clear()
    old_session = login(client, {"username": issued["username"], "password": issued["temporary_password"]})
    client.cookies.set("admin_session", organizer)
    reset = client.post(f"/api/admin/users/{issued['id']}/reset-password").json()
    assert reset["temporary_password"] != issued["temporary_password"]
    client.cookies.set("admin_session", old_session)
    assert client.get("/api/auth/me").status_code == 401  # a reset signs the account out
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": issued["username"], "password": issued["temporary_password"]}).status_code == 401
    assert client.post("/api/auth/login", json={"username": issued["username"], "password": reset["temporary_password"]}).status_code == 200

    client.cookies.set("admin_session", organizer)
    assert client.patch(f"/api/admin/users/{issued['id']}", json={"banned": True}).status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": issued["username"], "password": reset["temporary_password"]}).status_code == 401

    client.cookies.set("admin_session", organizer)
    log = client.get("/api/admin/audit").json()
    assert {"team.create", "user.create", "user.reset_password", "user.ban"} <= {entry["action"] for entry in log}
    assert all(entry["actor"] == "organizer" for entry in log)
    dumped = json.dumps(log)
    assert issued["temporary_password"] not in dumped and reset["temporary_password"] not in dumped


def test_zip_is_stored_and_queued_without_scoring(client, db, participant):
    content = make_zip()
    response = upload(client, content, name="my model.zip")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued" and body["queue_position"] == 1 and body["public_score"] is None
    assert (body["used"], body["limit"], body["remaining"]) == (1, 20, 19)
    assert body["sha256"] == hashlib.sha256(content).hexdigest() and body["size_bytes"] == len(content)
    row = db.get(Submission, body["id"])
    assert row.filename == "my model.zip" and row.team_id == participant["team_id"]
    assert storage.path_for(row.storage_key).read_bytes() == content
    assert not list(storage.temporary_path("x").parent.glob("*.part"))
    assert client.get(f"/api/submissions/{body['id']}").json()["status"] == "queued"
    for field in HIDDEN_FIELDS:
        assert field not in response.text


@pytest.mark.parametrize("content,name,status,code", [
    (make_zip(), "predictions.csv", 415, "not_zip"),
    (b"this is not a zip archive", "code.zip", 422, "zip_invalid"),
    (b"", "code.zip", 422, "zip_invalid"),
    (make_zip({"inference.py": "x", "model/w.bin": "x"}), "code.zip", 422, "zip_invalid"),
    (make_zip({"inference.py": "x", "requirements.txt": "x", "model/w.bin": "x"}), "code.zip", 422, "zip_invalid"),
    (make_zip({"code/inference.py": "x", "code/requirements.txt": "x", "code/model/w.bin": "x"}), "code.zip", 422, "zip_invalid"),
    (make_zip(extra={"../escape.txt": "x"}), "code.zip", 422, "zip_invalid"),
])
def test_bad_uploads_are_refused_without_using_an_attempt(client, db, participant, content, name, status, code):
    response = upload(client, content, name=name)
    assert response.status_code == status and response.json()["code"] == code, response.text
    assert db.scalars(select(Submission)).all() == []
    assert client.get("/api/submissions/me").json()["used"] == 0
    assert not list(storage.temporary_path("x").parent.glob("*.part"))


def test_upload_size_limit(client, db, participant, monkeypatch):
    import app.main as main
    import app.routers.submissions as submissions
    monkeypatch.setattr(main, "MAX_ZIP_BYTES", 200)
    monkeypatch.setattr(submissions, "MAX_ZIP_BYTES", 200)
    response = upload(client, make_zip(extra={"model/big.bin": bytes(range(256)) * 40}))
    assert response.status_code == 413 and response.json()["code"] == "zip_too_large"
    assert db.scalars(select(Submission)).all() == []
    assert client.post("/api/auth/login", content=b"x" * 70000, headers={"Content-Type": "application/json"}).status_code == 413


def test_team_limit_is_shared_by_all_accounts_and_never_resets(client, db, participant):
    settings = db.get(Settings, 1)
    settings.team_submission_limit = 2
    db.commit()
    assert upload(client).status_code == 202
    mate = add_account(db, participant["team_name"], "teammate")
    other = add_account(db, "Other team", "otherteam")
    login(client, mate)
    assert upload(client).json()["remaining"] == 0
    refused = upload(client)
    assert refused.status_code == 429 and refused.json()["code"] == "limit_reached"
    history = client.get("/api/submissions/me").json()
    assert (history["used"], history["limit"], history["remaining"]) == (2, 2, 0)
    assert {entry["submitted_by"] for entry in history["entries"]} == {"Protein Learners"}
    # Attempts used on an earlier day still count: there is no daily reset.
    for row in db.scalars(select(Submission)):
        row.created_at = now() - timedelta(days=3)
    db.commit()
    assert upload(client).status_code == 429
    login(client, other)
    assert upload(client).status_code == 202  # another team has its own allowance
    assert client.get(f"/api/submissions/{history['entries'][0]['id']}").status_code == 404


def test_time_gate(client, db, participant):
    settings = db.get(Settings, 1)
    settings.start_time = now() + timedelta(days=1)
    db.commit()
    assert upload(client).status_code == 403
    assert client.get("/api/competition").json()["submission_open"] is False
    settings.start_time = now() - timedelta(days=2)
    settings.end_time = now() - timedelta(days=1)
    db.commit()
    assert upload(client).json()["code"] == "closed"
    settings.end_time = now() + timedelta(days=1)
    settings.is_open = False
    db.commit()
    assert upload(client).status_code == 403


def test_csrf_and_login_rate_limit(client):
    assert client.post("/api/auth/logout", headers={"x-requested-with": "bad"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"origin": "https://evil.example"}).status_code == 403
    for _ in range(10):
        assert client.post("/api/auth/login", json={"username": "nobody", "password": "NotCorrect123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "nobody", "password": "NotCorrect123"}).status_code == 429


def test_settings_validation_and_audit(client, db, organizer):
    settings = db.get(Settings, 1)
    settings.is_open, settings.start_time, settings.end_time = False, None, None
    db.commit()
    client.cookies.set("admin_session", organizer)
    assert client.patch("/api/admin/competition", json={"is_open": True}).status_code == 422
    assert client.patch("/api/admin/competition", json={"is_open": True, "start_time": now().isoformat()}).status_code == 422
    assert client.patch("/api/admin/competition", json={"final_selection": "newest"}).status_code == 422
    assert client.patch("/api/admin/competition", json={"team_submission_limit": None}).status_code == 422
    saved = client.patch("/api/admin/competition", json={"team_submission_limit": 7, "count_failed": False, "final_selection": "best_private"})
    assert saved.status_code == 200 and saved.json()["team_submission_limit"] == 7
    public = client.get("/api/competition").json()
    assert public["limits"]["team_submissions"] == 7 and public["limits"]["required_entries"] == ["inference.py", "train.py", "requirements.txt", "model/"]
    # Undecided policies are organizer-only, not announced to participants.
    assert "final_selection" not in json.dumps(public) and "count_failed" not in json.dumps(public)
    assert db.scalars(select(AuditLog).where(AuditLog.action == "settings.update")).all()


EVALUATION_INPUT = ["test", "test-structures", "test-features", "sample-submission", "starter-kit"]
# The analysis charts sit in data/public but are for the organizers' presentation only.
ANALYSIS_CHARTS = ["class-distribution", "length-distribution"]
PARTICIPANT_FILES = ["train", "train-features", "train-structures", "validation-split"]


@pytest.mark.parametrize("kind", EVALUATION_INPUT + ANALYSIS_CHARTS + ["labels", "private"])
def test_evaluation_input_is_never_downloadable(client, db, participant, kind):
    assert client.get("/api/datasets/" + kind).status_code == 404


def test_metadata_does_not_describe_hidden_files(client, db):
    dataset = client.get("/api/competition").json()["dataset"]
    assert "train.csv" in dataset["files"] and "test.csv" not in dataset["files"]


def test_competition_info_does_not_name_the_topic(client, db):
    assert "Protein" in db.get(Competition, 1).title
    response = client.get("/api/competition")
    assert "title" not in response.json() and "protein" not in response.text.lower()


@pytest.mark.parametrize("kind", PARTICIPANT_FILES)
def test_dataset_release_window_and_approval(client, db, monkeypatch, kind):
    from datetime import datetime, timezone
    import app.routers.common as common
    stamp = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(common, "now", lambda: stamp)
    settings = db.get(Settings, 1)
    cases = [
        (True, None, None, "test-1", False),
        (True, stamp + timedelta(seconds=1), stamp + timedelta(hours=8), "test-1", False),
        (True, stamp, stamp + timedelta(hours=8), "test-1", True),
        (True, stamp, stamp + timedelta(hours=8), None, False),  # not approved by an organizer yet
        (True, stamp - timedelta(hours=8), stamp, "test-1", False),
        (False, stamp - timedelta(hours=1), stamp + timedelta(hours=1), "test-1", False),
    ]
    for opened, start, end, version, expected in cases:
        settings.is_open, settings.start_time, settings.end_time, settings.dataset_version = opened, start, end, version
        db.commit()
        response = client.get("/api/datasets/" + kind, headers={"Range": "bytes=0-9", "If-None-Match": "anything"})
        assert response.status_code in ([200, 206] if expected else [403])
        assert response.headers["cache-control"] == "no-store"
        info = client.get("/api/competition").json()
        assert info["dataset_available"] == expected and (info["dataset"] is not None) == expected
    settings.is_open, settings.finalized = True, True
    db.commit()
    assert client.get("/api/datasets/" + kind).status_code == 403


def test_public_baseline_is_code_only_even_when_competition_closed(client, db):
    import io
    import zipfile
    settings = db.get(Settings, 1)
    settings.is_open, settings.start_time, settings.end_time = False, None, None
    db.commit()
    response = client.get("/api/resources/baseline")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"baseline.py", "structure_features.py", "baseline.ipynb", "README.md", "structure-format.md", "requirements.txt"}
    for kind in PARTICIPANT_FILES:
        assert client.get("/api/datasets/" + kind).status_code == 403
    assert client.get("/api/competition").json()["dataset"] is None
    assert client.get("/api/resources/starter-kit").status_code == 404


def test_baseline_names_the_topic_so_only_admins_get_it_before_launch(client, db, organizer, monkeypatch):
    monkeypatch.setattr("app.routers.common.LAUNCH_AT", now() + timedelta(days=1))
    assert client.get("/api/resources/baseline").status_code == 403
    login(client, add_account(db, "Early Team", "earlyteam1"))
    assert client.get("/api/resources/baseline").status_code == 403
    client.cookies.set("admin_session", organizer)
    assert client.get("/api/resources/baseline").status_code == 200
    client.cookies.clear()
    monkeypatch.setattr("app.routers.common.LAUNCH_AT", now() - timedelta(seconds=1))
    assert client.get("/api/resources/baseline").status_code == 200


def test_dataset_approval_verify_and_lock(client, db, organizer):
    from app.config import DATA_DIR
    settings = db.get(Settings, 1)
    settings.dataset_version = None
    db.commit()
    assert client.get("/api/admin/dataset").status_code == 401
    client.cookies.set("admin_session", organizer)
    before = client.get("/api/admin/dataset").json()
    assert before["version"] == "test-1" and before["approved"]["version"] is None
    assert {"train.csv", "example_io.zip"} <= {entry["name"] for entry in before["files"]}
    assert "test.csv" not in json.dumps(before)
    assert client.post("/api/admin/dataset/lock", json={"locked": True}).status_code == 409
    approved = client.post("/api/admin/dataset/approve").json()
    train = next(entry for entry in approved["files"] if entry["name"] == "train.csv")
    assert train["approved_sha256"] == hashlib.sha256((DATA_DIR / "public/train.csv").read_bytes()).hexdigest()
    assert approved["approved"]["by"] == "organizer" and client.post("/api/admin/dataset/verify").json()["ok"] is True
    assert client.post("/api/admin/dataset/lock", json={"locked": True}).json()["approved"]["locked"] is True
    assert client.post("/api/admin/dataset/approve").status_code == 409
    assert client.post("/api/admin/dataset/lock", json={"locked": False}).status_code == 409  # competition is open
    original = (DATA_DIR / "public/train_features.csv").read_bytes()
    try:
        (DATA_DIR / "public/train_features.csv").write_bytes(original + b"tampered\n")
        assert client.post("/api/admin/dataset/verify").json() == {"ok": False, "changed": ["train_features.csv"]}
    finally:
        (DATA_DIR / "public/train_features.csv").write_bytes(original)
