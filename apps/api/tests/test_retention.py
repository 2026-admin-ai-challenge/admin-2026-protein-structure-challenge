import json

import pytest
from sqlalchemy import select

from app import files, leaderboard, storage
from app.models import AuditLog, LeaderboardEntry, Settings, SubmissionFile
from app.evaluators.base import Outcome
from app.evaluators.mock import MockEvaluator
from app.worker import claim, finish, process_one
from conftest import add_account, login, make_zip, upload


@pytest.fixture(autouse=True)
def best_only(monkeypatch, tmp_path):
    monkeypatch.setattr(files, "ZIP_RETENTION", "best_public")
    monkeypatch.setattr(files, "SUBMISSION_DIR", tmp_path)
    monkeypatch.setattr(storage, "SUBMISSION_DIR", tmp_path)


def submit(client, **controls):
    return upload(client, make_zip(extra={"mock.json": json.dumps(controls)})).json()["id"]


def file_for(db, id):
    return db.scalar(select(SubmissionFile).where(SubmissionFile.submission_id == id))


def score_next(db):
    return process_one(db, MockEvaluator(), "retention-test")


def test_lower_score_new_record_and_tie_keep_one_zip_and_all_history(client, db, participant):
    first = submit(client, public=0.4, private=0.8)
    score_next(db)
    low = submit(client, public=0.3, private=0.9)
    score_next(db)
    assert file_for(db, first).deleted_at is None and file_for(db, low).deleted_at
    high = submit(client, public=0.9, private=0.4)
    score_next(db)
    tie = submit(client, public=0.9, private=0.9)
    score_next(db)
    kept = db.scalars(select(SubmissionFile).where(SubmissionFile.deleted_at.is_(None))).all()
    assert [f.submission_id for f in kept] == [high]
    assert storage.path_for(kept[0].storage_key).exists()
    assert files.check(db, with_hashes=True)["ok"]
    result = client.get("/api/submissions/me").json()
    assert len(result["entries"]) == 4 and result["used"] == 4
    assert [s["id"] for s in result["entries"] if s["is_best_public"]] == [high]
    assert {s["id"]: s["public_score"] for s in result["entries"]} == {first: 0.4, low: 0.3, high: 0.9, tie: 0.9}
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "file.retention")).all()) == 3


def test_kept_zip_follows_the_leaderboard_tie_rule(client, db, participant, monkeypatch):
    # Changing the tie rule in one place (e.g. smaller ZIP first) must move both the
    # board entry and the kept ZIP; otherwise the final submission's ZIP could be gone.
    def later_wins(rows, field="public_score"):
        candidates = [row for row in rows if getattr(row, field) is not None]
        return max(candidates, key=lambda s: (getattr(s, field), s.id), default=None)
    monkeypatch.setattr(leaderboard, "best_of", later_wins)
    first = submit(client, public=0.9, private=0.1)
    score_next(db)
    tie = submit(client, public=0.9, private=0.2)
    score_next(db)
    entry = db.scalar(select(LeaderboardEntry).where(LeaderboardEntry.board == "public"))
    assert entry.submission_id == tie
    assert file_for(db, tie).deleted_at is None and file_for(db, first).deleted_at
    result = client.get("/api/submissions/me").json()
    assert [s["id"] for s in result["entries"] if s["is_best_public"]] == [tie]


def test_pending_and_retryable_server_failure_are_protected(client, db, participant):
    first = submit(client, public=0.8)
    waiting = submit(client, public=0.2)
    score_next(db)
    assert file_for(db, waiting).deleted_at is None
    running = claim(db, "other-worker")
    files.mark_unneeded(db, db.get(Settings, 1))
    db.commit()
    assert running.id == waiting and file_for(db, waiting).deleted_at is None
    finish(db, waiting, "other-worker", Outcome(ok=False, failure_code="system_error"), "mock")
    assert file_for(db, waiting).deleted_at is None
    failed = submit(client, fail="runtime_error")
    score_next(db)
    assert file_for(db, failed).deleted_at
    assert file_for(db, first).deleted_at is None


def test_teams_are_independent(client, db, participant):
    first = submit(client, public=0.6)
    score_next(db)
    other = add_account(db, "Other retention team", "retentionother")
    login(client, other)
    second = submit(client, public=0.1)
    score_next(db)
    assert file_for(db, first).deleted_at is None and file_for(db, second).deleted_at is None


def test_frozen_board_preserves_old_zip_until_unfreeze(client, db, participant):
    old = submit(client, public=0.4)
    score_next(db)
    settings = db.get(Settings, 1)
    settings.frozen = True
    db.commit()
    new = submit(client, public=0.9)
    score_next(db)
    assert file_for(db, old).deleted_at is None and file_for(db, new).deleted_at is None
    from app.leaderboard import rebuild
    settings.frozen = False
    rebuild(db)
    files.mark_unneeded(db, settings)
    db.commit()
    files.purge_deleted(db)
    assert file_for(db, old).deleted_at and file_for(db, new).deleted_at is None


def test_best_private_final_preserves_its_model(client, db, participant):
    db.get(Settings, 1).final_selection = "best_private"
    db.commit()
    private = submit(client, public=0.4, private=0.9)
    score_next(db)
    public = submit(client, public=0.9, private=0.4)
    score_next(db)
    assert file_for(db, private).deleted_at is None and file_for(db, public).deleted_at is None


def test_disk_failure_is_retryable_after_score_commit(client, db, participant, monkeypatch):
    old = submit(client, public=0.4)
    score_next(db)
    old_path = storage.path_for(file_for(db, old).storage_key)
    discard = storage.discard
    new = submit(client, public=0.9)
    def denied(path):
        raise PermissionError("disk temporarily unavailable")
    monkeypatch.setattr(storage, "discard", denied)
    done = score_next(db)
    assert done.status == "succeeded" and done.public_score == 0.9
    assert file_for(db, old).deleted_at and old_path.exists()
    monkeypatch.setattr(storage, "discard", discard)
    files.purge_deleted(db)
    assert not old_path.exists() and storage.path_for(file_for(db, new).storage_key).exists()


def test_failed_db_commit_never_deletes_zip(client, db, participant, monkeypatch):
    old = submit(client, public=0.4)
    score_next(db)
    new = submit(client, public=0.9)
    claim(db, "rollback-worker")
    path = storage.path_for(file_for(db, old).storage_key)
    def fail_commit():
        raise RuntimeError("database commit failed")
    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database commit failed"):
        finish(db, new, "rollback-worker", Outcome(ok=True, scores={"public": 0.9, "private": 0.3}), "mock")
    db.rollback()
    assert path.exists() and file_for(db, old).deleted_at is None
