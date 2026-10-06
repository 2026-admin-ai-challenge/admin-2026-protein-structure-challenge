"""Clearing a finished competition so the same site can host the next one.

Submissions, their ZIPs and both leaderboards are archived under ARCHIVE_DIR and removed
from the database. Teams, accounts, policies, dataset approval and the audit log stay.
"""
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select

from . import storage
from .config import ARCHIVE_DIR, WORKER_STALE_SECONDS
from .models import LeaderboardEntry, Submission, SubmissionFile, now

CONFIRM_PHRASE = "초기화"


def _snapshot(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def scoring_now(db):
    """Running submissions whose worker is still reporting. Abandoned ones may be cleared."""
    cutoff = now() - timedelta(seconds=WORKER_STALE_SECONDS)
    return db.scalar(select(func.count(Submission.id)).where(Submission.status == "running", Submission.heartbeat_at >= cutoff))


def clear(db, settings):
    """Removes every submission, file record and leaderboard entry and returns the competition
    to closed, unscheduled and not finalized. The caller holds the settings lock and commits.

    The removed rows are written to <archive>/records.json first. Returns (summary, moves):
    the ZIPs to move into the archive with move_files() once the commit succeeded."""
    submissions = db.scalars(select(Submission).order_by(Submission.id)).all()
    stored = db.scalars(select(SubmissionFile).order_by(SubmissionFile.id)).all()
    entries = db.scalars(select(LeaderboardEntry).order_by(LeaderboardEntry.id)).all()
    summary = {"archive": None, "submissions": len(submissions), "files": 0, "leaderboard_entries": len(entries),
               "previous": {key: getattr(settings, key) for key in ["start_time", "end_time", "frozen", "finalized"]}}
    moves = []
    if submissions or entries:
        stamp = now()
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix=f"reset-{stamp:%Y%m%dT%H%M%SZ}-", dir=ARCHIVE_DIR))
        records = {"reset_at": stamp, "settings": _snapshot(settings), "submissions": [_snapshot(r) for r in submissions],
                   "submission_files": [_snapshot(r) for r in stored], "leaderboard_entries": [_snapshot(r) for r in entries]}
        (folder / "records.json").write_text(json.dumps(records, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        moves = [(storage.path_for(f.storage_key), folder / "zips" / f"team{f.team_id}-submission{f.submission_id}.zip")
                 for f in stored if not f.deleted_at]
        summary["archive"], summary["files"] = str(folder), len(moves)
    # Children first: leaderboard entries and file records point at submissions.
    db.execute(delete(LeaderboardEntry))
    db.execute(delete(SubmissionFile))
    db.execute(delete(Submission))
    settings.is_open = settings.frozen = settings.finalized = False
    settings.start_time = settings.end_time = None
    db.flush()
    return summary, moves


def move_files(moves):
    """Moves ZIPs into the archive. Returns the ones that stayed where they were, with the reason."""
    failed = []
    for source, target in moves:
        try:
            target.parent.mkdir(exist_ok=True)
            os.replace(source, target)
        except OSError as error:
            failed.append(f"{source.name}: {error.strerror or error}")
    return failed


def discard_archive(summary):
    """Removes the records file of a reset whose commit failed, so the archive only holds real resets."""
    if summary["archive"]:
        folder = Path(summary["archive"])
        storage.discard(folder / "records.json")
        folder.rmdir()
