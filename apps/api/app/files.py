"""Managing stored submission ZIPs through the submission_files table."""
import time
import logging

from sqlalchemy import func, select

from . import storage
from .config import EVALUATOR, SUBMISSION_DIR, ZIP_RETENTION
from .audit import record
from .leaderboard import _moment
from .dataset import hash_file
from .models import LeaderboardEntry, Submission, SubmissionFile, now

log = logging.getLogger(__name__)


def best_public_id(db, team_id):
    rows = db.scalars(select(Submission).where(
        Submission.team_id == team_id, Submission.status == "succeeded",
        Submission.evaluator == EVALUATOR, Submission.public_score.is_not(None),
    )).all()
    return min(rows, key=lambda s: (-s.public_score, _moment(s), s.id)).id if rows else None


def mark_unneeded(db, settings, team_id=None):
    """Mark obsolete ZIPs inside the score transaction; delete bytes only after commit.

    Keep pending runs, retryable server failures, best Public models and every ZIP
    referenced by a frozen/final board. A best-Private final also needs that model.
    Scores, predictions, logs, attempt counts and file hashes are never removed.
    """
    if ZIP_RETENTION != "best_public":
        return []
    scored = select(Submission).where(Submission.status == "succeeded", Submission.evaluator == EVALUATOR)
    if team_id is not None:
        scored = scored.where(Submission.team_id == team_id)
    teams = {}
    for row in db.scalars(scored):
        teams.setdefault(row.team_id, []).append(row)
    protected = ranked_submission_ids(db)
    for rows in teams.values():
        for field in (["public_score", "private_score"] if settings.final_selection == "best_private" else ["public_score"]):
            candidates = [s for s in rows if getattr(s, field) is not None]
            if candidates:
                protected.add(min(candidates, key=lambda s: (-getattr(s, field), _moment(s), s.id)).id)
    query = select(SubmissionFile, Submission).join(Submission, Submission.id == SubmissionFile.submission_id).where(
        SubmissionFile.deleted_at.is_(None), Submission.status.in_(["succeeded", "failed"]),
    )
    if team_id is not None:
        query = query.where(SubmissionFile.team_id == team_id)
    query = query.with_for_update(of=SubmissionFile)
    deleted = []
    for stored, submission in db.execute(query):
        if submission.id in protected or submission.failure_code == "system_error":
            continue
        stored.deleted_at, stored.deleted_by = now(), "retention-worker"
        stored.delete_reason = "최고 점수 ZIP 보관 정책에 따른 자동 정리"
        record(db, "retention-worker", "file.retention", f"file:{stored.id}", {
            "submission": submission.id, "team_id": stored.team_id, "reason": stored.delete_reason,
        })
        deleted.append(stored.id)
    db.flush()
    return deleted


def purge_deleted(db):
    """Retry committed deletions after restart or a temporary disk failure."""
    for stored in db.scalars(select(SubmissionFile).where(SubmissionFile.deleted_at.is_not(None))):
        try:
            storage.discard(storage.path_for(stored.storage_key))
        except OSError:
            log.exception("could not remove retired ZIP for submission %s; will retry", stored.submission_id)

STALE_UPLOAD_SECONDS = 3600


def usage_by_team(db):
    """{team_id: (kept files, kept bytes)}. Deleted files no longer use space."""
    rows = db.execute(
        select(SubmissionFile.team_id, func.count(SubmissionFile.id), func.coalesce(func.sum(SubmissionFile.size_bytes), 0))
        .where(SubmissionFile.deleted_at.is_(None)).group_by(SubmissionFile.team_id)
    ).all()
    return {team_id: (count, int(total)) for team_id, count, total in rows}


def ranked_submission_ids(db):
    """Submissions a leaderboard currently points at. Their files must be kept."""
    return set(db.scalars(select(LeaderboardEntry.submission_id)))


def check(db, with_hashes=False):
    """Compares the database with the disk.

    missing            recorded as kept, but the ZIP is not on disk
    size_mismatch      on disk with a different size than recorded
    hash_mismatch      (only with_hashes) content differs from the recorded SHA-256
    deleted_present    recorded as deleted, but the ZIP is still on disk
    orphans            ZIPs on disk that no record points at
    stale_uploads      interrupted uploads older than an hour
    """
    report = {"checked": 0, "missing": [], "size_mismatch": [], "hash_mismatch": [], "deleted_present": [],
              "orphans": [], "stale_uploads": 0}
    known = set()
    for record in db.scalars(select(SubmissionFile).order_by(SubmissionFile.id)):
        known.add(record.storage_key)
        path = storage.path_for(record.storage_key)
        label = {"file_id": record.id, "submission_id": record.submission_id, "team_id": record.team_id}
        if record.deleted_at:
            if path.exists():
                report["deleted_present"].append(label)
            continue
        report["checked"] += 1
        if not path.exists():
            report["missing"].append(label)
        elif path.stat().st_size != record.size_bytes:
            report["size_mismatch"].append(label)
        elif with_hashes and hash_file(path) != record.sha256:
            report["hash_mismatch"].append(label)
    if SUBMISSION_DIR.exists():
        for path in SUBMISSION_DIR.glob("*/*.zip"):
            if path.parent.name != "incoming" and path.stem not in known:
                report["orphans"].append(f"{path.parent.name}/{path.name}")
        cutoff = time.time() - STALE_UPLOAD_SECONDS
        report["stale_uploads"] = sum(1 for part in (SUBMISSION_DIR / "incoming").glob("*.part") if part.stat().st_mtime < cutoff)
    report["ok"] = not any(report[key] for key in ["missing", "size_mismatch", "hash_mismatch", "deleted_present", "orphans"])
    return report
