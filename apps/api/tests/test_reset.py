import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app import storage
from app.config import ARCHIVE_DIR, WORKER_STALE_SECONDS
from app.evaluators.mock import MockEvaluator
from app.models import AuditLog, LeaderboardEntry, Settings, Submission, SubmissionFile, Team, User, now
from app.worker import process_one
from conftest import login, make_zip, upload

MOCK = MockEvaluator()
CONFIRM = {"confirm": "초기화"}


def mock_zip(**controls):
    return make_zip(extra={"mock.json": json.dumps(controls)})


def test_reset_archives_results_and_the_next_competition_starts_clean(client, db, participant, organizer):
    best = mock_zip(public=0.9, private=0.8)
    first = upload(client, best).json()
    second = upload(client, mock_zip(public=0.4, private=0.3)).json()
    process_one(db, MOCK, "worker-a")
    process_one(db, MOCK, "worker-a")
    keys = {f.submission_id: f.storage_key for f in db.scalars(select(SubmissionFile))}
    client.cookies.set("admin_session", organizer)
    assert client.patch("/api/admin/competition", json={"is_open": False, "frozen": True}).status_code == 200
    assert client.post("/api/admin/leaderboard/finalize").status_code == 200

    response = client.post("/api/admin/competition/reset", json=CONFIRM)
    assert response.status_code == 200, response.text
    result = response.json()
    # One team: its Public and final (private) entries.
    assert (result["submissions"], result["files"], result["leaderboard_entries"], result["not_moved"]) == (2, 2, 2, [])
    assert result["previous"]["finalized"] is True
    settings = result["settings"]
    assert not (settings["is_open"] or settings["frozen"] or settings["finalized"])
    assert settings["start_time"] is None and settings["end_time"] is None
    assert settings["team_submission_limit"] == 10  # policies are kept
    for model in [Submission, SubmissionFile, LeaderboardEntry]:
        assert db.scalars(select(model)).all() == []

    # Everything removed is in the archive: the rows as JSON and the ZIPs themselves.
    folder = Path(result["archive"])
    assert folder.parent == ARCHIVE_DIR
    records = json.loads((folder / "records.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in records["submissions"]] == [first["id"], second["id"]]
    assert records["submissions"][0]["private_score"] == 0.8 and records["settings"]["finalized"] is True
    assert {row["board"] for row in records["leaderboard_entries"]} == {"public", "private"}
    for submission_id, key in keys.items():
        assert not storage.path_for(key).exists()
        assert (folder / "zips" / f"team{participant['team_id']}-submission{submission_id}.zip").exists()
    assert (folder / "zips" / f"team{participant['team_id']}-submission{first['id']}.zip").read_bytes() == best

    # Teams, accounts and the dataset approval stay; the reset itself is on record.
    assert db.get(User, participant["id"]) and db.get(Team, participant["team_id"])
    assert db.get(Settings, 1).dataset_version == "test-1"
    log = db.scalar(select(AuditLog).where(AuditLog.action == "competition.reset"))
    assert log.actor == "organizer" and log.ok and json.loads(log.detail)["submissions"] == 2

    assert client.get("/api/leaderboard").json()["entries"] == []
    assert client.get("/api/leaderboard?board=final").status_code == 403
    assert client.get("/api/competition").json()["submissions"] == 0

    # The next competition needs a new schedule, and the team has all its attempts again.
    assert client.patch("/api/admin/competition", json={"is_open": True}).status_code == 422
    stamp = now()
    schedule = {"start_time": (stamp - timedelta(minutes=1)).isoformat(), "end_time": (stamp + timedelta(hours=1)).isoformat()}
    assert client.patch("/api/admin/competition", json={"is_open": True, **schedule}).status_code == 200
    client.cookies.clear()
    login(client, participant)
    again = upload(client)
    assert again.status_code == 202 and (again.json()["used"], again.json()["remaining"]) == (1, 9)


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


def test_reset_of_an_empty_competition_leaves_no_archive(client, db, organizer):
    db.get(Settings, 1).is_open = False
    db.commit()
    client.cookies.set("admin_session", organizer)
    response = client.post("/api/admin/competition/reset", json=CONFIRM)
    assert response.status_code == 200
    assert (response.json()["archive"], response.json()["submissions"]) == (None, 0)
    assert db.get(Settings, 1).start_time is None


def test_a_zip_missing_from_disk_does_not_stop_the_reset(client, db, participant, organizer):
    upload(client)
    gone = upload(client).json()
    storage.discard(storage.path_for(db.get(Submission, gone["id"]).storage_key))
    db.get(Settings, 1).is_open = False
    db.commit()
    client.cookies.set("admin_session", organizer)
    result = client.post("/api/admin/competition/reset", json=CONFIRM).json()
    assert result["submissions"] == 2 and len(result["not_moved"]) == 1
    assert len(list((Path(result["archive"]) / "zips").glob("*.zip"))) == 1
    failed = db.scalar(select(AuditLog).where(AuditLog.action == "competition.reset", AuditLog.ok.is_(False)))
    assert failed.target == "archive"
