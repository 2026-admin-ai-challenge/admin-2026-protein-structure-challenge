"""Managing stored submission ZIPs through the submission_files table."""
import time

from sqlalchemy import func, select

from . import storage
from .config import SUBMISSION_DIR
from .dataset import hash_file
from .models import LeaderboardEntry, SubmissionFile

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
