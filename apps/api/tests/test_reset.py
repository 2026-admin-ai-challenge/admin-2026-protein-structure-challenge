import json
import os
import time
import uuid
from datetime import timedelta

from sqlalchemy import select

from app import files, reset, storage
from app.config import WORKER_STALE_SECONDS
from app.evaluators.mock import MockEvaluator
from app.models import AuditLog, LeaderboardEntry, Settings, Submission, SubmissionFile, Team, User, Worker, now
from app.worker import process_one
from conftest import login, make_zip, upload

MOCK = MockEvaluator()
CONFIRM = {"confirm": "초기화"}


def mock_zip(**controls):
    return make_zip(extra={"mock.json": json.dumps(controls)})


def test_reset_deletes_results_and_the_next_competition_starts_clean(client, db, participant, organizer):
    upload(client, mock_zip(public=0.9, private=0.8))
    upload(client, mock_zip(public=0.4, private=0.3))
    process_one(db, MOCK, "worker-a")
    process_one(db, MOCK, "worker-a")
    keys = db.scalars(select(SubmissionFile.storage_key)).all()
    # Leftovers on disk: a ZIP no record points at, an interrupted upload and one still arriving.
    orphan = storage.path_for(uuid.uuid4().hex)
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(make_zip())
    stale, arriving = storage.temporary_path("stale-upload"), storage.temporary_path("arriving-upload")
    stale.parent.mkdir(parents=True, exist_ok=True)
    for part in [stale, arriving]:
        part.write_bytes(b"partial")
    os.utime(stale, (time.time() - files.STALE_UPLOAD_SECONDS - 60,) * 2)
    client.cookies.set("admin_session", organizer)
    assert client.patch("/api/admin/competition", json={"is_open": False, "frozen": True}).status_code == 200
    assert client.post("/api/admin/leaderboard/finalize").status_code == 200
    assert db.scalars(select(Worker)).all() and len(db.scalars(select(AuditLog)).all()) >= 2

    response = client.post("/api/admin/competition/reset", json=CONFIRM)
    assert response.status_code == 200, response.text
    result = response.json()
    # One team: its Public and final (private) entries.
    assert (result["submissions"], result["files"], result["leaderboard_entries"], result["not_deleted"]) == (2, 2, 2, [])
    assert result["previous"]["finalized"] is True and result["audit_entries"] >= 2
    settings = result["settings"]
    assert not (settings["is_open"] or settings["frozen"] or settings["finalized"])
    assert settings["start_time"] is None and settings["end_time"] is None
    assert settings["team_submission_limit"] == 20  # policies are kept
    for model in [Submission, SubmissionFile, LeaderboardEntry, Worker]:
        assert db.scalars(select(model)).all() == []
    # The ZIPs are gone from disk with any orphan and stale upload; nothing was kept aside.
    assert len(keys) == 2 and not any(storage.path_for(key).exists() for key in keys)
    assert not orphan.exists() and not stale.exists() and arriving.exists()
    arriving.unlink()

    # Teams, accounts and the dataset approval stay. The old audit log is gone and
    # the reset is the first entry of the new one.
    assert db.get(User, participant["id"]) and db.get(Team, participant["team_id"])
    assert db.get(Settings, 1).dataset_version == "test-1"
    [log] = db.scalars(select(AuditLog)).all()
    assert (log.id, log.action, log.actor, log.ok) == (1, "competition.reset", "organizer", True)
    assert json.loads(log.detail)["submissions"] == 2

    # The team stays, now without a score.
    assert [e["rank"] for e in client.get("/api/leaderboard").json()["entries"]] == [None]
    assert client.get("/api/leaderboard?board=final").status_code == 403
    assert client.get("/api/competition").json()["submissions"] == 0

    # The next competition needs a new schedule; the team has all its attempts again and numbering restarts.
    assert client.patch("/api/admin/competition", json={"is_open": True}).status_code == 422
    stamp = now()
    schedule = {"start_time": (stamp - timedelta(minutes=1)).isoformat(), "end_time": (stamp + timedelta(hours=1)).isoformat()}
    assert client.patch("/api/admin/competition", json={"is_open": True, **schedule}).status_code == 200
    client.cookies.clear()
    login(client, participant)
    again = upload(client)
    assert again.status_code == 202 and (again.json()["used"], again.json()["remaining"]) == (1, 19)
    assert again.json()["id"] == 1 and db.scalar(select(SubmissionFile.id)) == 1


def test_reset_needs_the_phrase_a_closed_competition_and_no_live_scoring(client, db, participant, organizer):
    upload(client)
    running = upload(client).json()
    assert client.post("/api/admin/competition/reset", json=CONFIRM).status_code == 403
    client.cookies.set("admin_session", organizer)
    assert client.post("/api/admin/competition/reset", json={"confirm": "reset"}).status_code == 422
    refused = client.post("/api/admin/competition/reset", json=CONFIRM)
    assert refused.status_code == 409 and "닫아" in refused.json()["detail"]

    assert client.patch("/api/admin/competition", json={"is_open": False}).status_code == 200
    row = db.get(Submission, running["id"])
    row.status, row.worker_id, row.heartbeat_at = "running", "worker-a", now()
    db.commit()
    refused = client.post("/api/admin/competition/reset", json=CONFIRM)
    assert refused.status_code == 409 and "1건" in refused.json()["detail"]
    assert len(db.scalars(select(Submission)).all()) == 2

    # A worker that stopped reporting no longer blocks the reset; queued work is cleared too.
    row.heartbeat_at = now() - timedelta(seconds=WORKER_STALE_SECONDS + 10)
    db.commit()
    response = client.post("/api/admin/competition/reset", json=CONFIRM)
    assert response.status_code == 200 and response.json()["submissions"] == 2


def test_reset_of_an_empty_competition(client, db, organizer):
    db.get(Settings, 1).is_open = False
    db.commit()
    client.cookies.set("admin_session", organizer)
    response = client.post("/api/admin/competition/reset", json=CONFIRM)
    assert response.status_code == 200
    assert (response.json()["submissions"], response.json()["files"]) == (0, 0)
    assert db.get(Settings, 1).start_time is None


def test_a_zip_that_cannot_be_deleted_is_reported_and_kept(client, db, participant, organizer, monkeypatch):
    upload(client)
    gone = upload(client).json()
    locked = upload(client).json()
    storage.discard(storage.path_for(db.get(Submission, gone["id"]).storage_key))  # already missing: not a failure
    stuck = storage.path_for(db.get(Submission, locked["id"]).storage_key)
    discard = storage.discard

    def refuse(path):
        if path == stuck:
            raise PermissionError(13, "Permission denied")
        discard(path)

    monkeypatch.setattr(reset.storage, "discard", refuse)
    db.get(Settings, 1).is_open = False
    db.commit()
    client.cookies.set("admin_session", organizer)
    result = client.post("/api/admin/competition/reset", json=CONFIRM).json()
    assert result["submissions"] == 3 and result["not_deleted"] == [f"{stuck.name}: Permission denied"]
    assert stuck.exists() and db.scalars(select(Submission)).all() == []
    failed = db.scalar(select(AuditLog).where(AuditLog.action == "competition.reset", AuditLog.ok.is_(False)))
    assert failed.target == "files"
