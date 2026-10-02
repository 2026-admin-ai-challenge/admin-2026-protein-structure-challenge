"""Response shapes and gates shared by the routers. docs/api-contract.md mirrors these."""
from sqlalchemy import func, select

from ..config import EVALUATOR, INFERENCE_TIMEOUT_SECONDS, MAX_ZIP_BYTES, ZIP_REQUIRED
from ..dataset import metadata
from ..models import Submission, Team, now, utc

PENDING = ("queued", "running")


def submission_open(settings, stamp=None):
    stamp = stamp or now()
    return bool(settings and settings.is_open and not settings.finalized
                and settings.start_time and settings.end_time
                and utc(settings.start_time) <= stamp < utc(settings.end_time))


def dataset_available(settings, stamp=None):
    """Downloads open only during the competition window and after an organizer approved the dataset."""
    return bool(submission_open(settings, stamp) and settings.dataset_version and metadata() is not None)


def used_attempts(db, team_id):
    return db.scalar(select(func.count(Submission.id)).where(Submission.team_id == team_id, Submission.counted.is_(True)))


def user_view(user, db):
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "team_id": user.team_id, "team_name": db.get(Team, user.team_id).name, "role": user.role}


def settings_view(s):
    return {"is_open": s.is_open, "start_time": s.start_time, "end_time": s.end_time,
            "team_submission_limit": s.team_submission_limit, "frozen": s.frozen, "finalized": s.finalized}


def admin_settings_view(s):
    return {**settings_view(s), "count_failed": s.count_failed, "final_selection": s.final_selection}


def limits_view(s):
    return {"zip_bytes": MAX_ZIP_BYTES, "inference_seconds": INFERENCE_TIMEOUT_SECONDS,
            "team_submissions": s.team_submission_limit, "required_entries": list(ZIP_REQUIRED)}


def queue_positions(db):
    """1-based place in line for every submission that is waiting or running."""
    ids = db.scalars(select(Submission.id).where(Submission.status.in_(PENDING)).order_by(Submission.id)).all()
    return {id: index + 1 for index, id in enumerate(ids)}


def submission_view(row, positions=None):
    """What a team may see. Never includes the Private score or container output."""
    return {
        "id": row.id, "filename": row.filename, "status": row.status, "failure_code": row.failure_code,
        "error_message": row.error_message, "public_score": row.public_score, "counted": row.counted,
        "size_bytes": row.size_bytes, "sha256": row.sha256, "evaluator": row.evaluator,
        "queue_position": (positions or {}).get(row.id),
        "created_at": row.created_at, "started_at": row.started_at, "finished_at": row.finished_at,
    }


def evaluator_name():
    return EVALUATOR
