"""Clearing a finished competition so the same site can host the next one.

Submissions, their ZIPs, both leaderboards, recorded special awards, the audit log and worker
status are deleted for good and numbering starts again from 1; nothing is kept aside, so
organizers back up first if they need them. Teams, accounts, policies and dataset approval stay.
"""
import time
from datetime import timedelta

from sqlalchemy import delete, func, select, text

from . import files, storage
from .config import SUBMISSION_DIR, WORKER_STALE_SECONDS
from .models import AuditLog, LeaderboardEntry, RateBucket, SpecialAward, Submission, SubmissionFile, Worker, now

CONFIRM_PHRASE = "초기화"
# Children before parents: leaderboard entries and file records point at submissions.
TABLES = [LeaderboardEntry, SubmissionFile, Submission, SpecialAward, AuditLog, Worker, RateBucket]


def scoring_now(db):
    """Running submissions whose worker is still reporting. Abandoned ones may be cleared."""
    cutoff = now() - timedelta(seconds=WORKER_STALE_SECONDS)
    return db.scalar(select(func.count(Submission.id)).where(Submission.status == "running", Submission.heartbeat_at >= cutoff))


def clear(db, settings):
    """Empties the competition tables and returns the competition to closed, unscheduled and
    not finalized. The caller holds the settings lock, records the reset and commits."""
    summary = {"submissions": db.scalar(select(func.count(Submission.id))),
               "files": db.scalar(select(func.count(SubmissionFile.id)).where(SubmissionFile.deleted_at.is_(None))),
               "leaderboard_entries": db.scalar(select(func.count(LeaderboardEntry.id))),
               "special_awards": db.scalar(select(func.count(SpecialAward.kind))),
               "audit_entries": db.scalar(select(func.count(AuditLog.id))),
               "previous": {key: getattr(settings, key) for key in ["start_time", "end_time", "frozen", "finalized"]}}
    if db.bind.dialect.name == "postgresql":
        # Also restarts the ID sequences, inside this transaction.
        db.execute(text(f"TRUNCATE {', '.join(model.__table__.name for model in TABLES)} RESTART IDENTITY"))
    else:
        # SQLite hands out IDs from 1 again once a table is empty.
        for model in TABLES:
            db.execute(delete(model))
    settings.is_open = settings.frozen = settings.finalized = False
    settings.start_time = settings.end_time = None
    db.flush()
    return summary


def delete_files():
    """Deletes every stored ZIP, including ones no record pointed at, and interrupted uploads
    older than an hour. Returns the files still on disk, with the reason."""
    if not SUBMISSION_DIR.exists():
        return []
    cutoff = time.time() - files.STALE_UPLOAD_SECONDS
    targets = [path for path in SUBMISSION_DIR.glob("*/*.zip") if path.parent.name != "incoming"]
    targets += [path for path in (SUBMISSION_DIR / "incoming").glob("*.part") if path.stat().st_mtime < cutoff]
    failed = []
    for path in targets:
        try:
            storage.discard(path)
        except OSError as error:
            failed.append(f"{path.name}: {error.strerror or error}")
    return failed
