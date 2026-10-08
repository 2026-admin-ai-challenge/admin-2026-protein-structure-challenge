"""Receiving model ZIPs. Nothing is executed here: a ZIP is stored, recorded as
`queued`, and scored later by the separate worker process."""
from pathlib import Path
from urllib.parse import unquote
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from .. import storage, zipcheck
from ..config import MAX_ZIP_BYTES
from ..db import get_db
from ..errors import ApiError
from ..models import Settings, Submission, SubmissionFile, Team, User, now
from ..security import current_user, rate_limit
from .common import queue_positions, submission_open, submission_view, used_attempts

router = APIRouter(prefix="/api/submissions")


def megabytes(size):
    return f"{size / (1024 * 1024):.0f} MB"


def quota_view(db, team_id, settings):
    used = used_attempts(db, team_id)
    return {"used": used, "limit": settings.team_submission_limit, "remaining": max(0, settings.team_submission_limit - used)}


def precheck(db, user):
    """Cheap refusals before any bytes are read. Repeated under locks in `accept`."""
    rate_limit(db, "upload:" + str(user.id), 10)
    settings = db.get(Settings, 1)
    if not submission_open(settings):
        raise ApiError(403, "closed", "현재 제출 기간이 아닙니다.")
    if used_attempts(db, user.team_id) >= settings.team_submission_limit:
        raise ApiError(429, "limit_reached", "팀의 제출 횟수를 모두 사용했습니다.")


def accept(db, user, filename, key, temporary, size, digest):
    # Serialize with settings changes, finalization and the team's other accounts,
    # so two simultaneous uploads can never exceed the team limit.
    settings = db.scalar(select(Settings).where(Settings.id == 1).with_for_update())
    team = db.scalar(select(Team).where(Team.id == user.team_id).with_for_update())
    locked = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if locked.banned:
        raise HTTPException(403, "계정에 접근할 수 없습니다.")
    stamp = now()
    if not submission_open(settings, stamp):
        raise ApiError(403, "closed", "현재 제출 기간이 아닙니다.")
    if used_attempts(db, team.id) >= settings.team_submission_limit:
        raise ApiError(429, "limit_reached", "팀의 제출 횟수를 모두 사용했습니다.")
    final = storage.commit(temporary, key)
    row = Submission(user_id=user.id, team_id=team.id, filename=filename, status="queued", counted=True, created_at=stamp)
    # The file record shares team_id and submission_id with the submission and is written
    # in the same transaction, so neither can exist without the other.
    row.file = SubmissionFile(team_id=team.id, uploaded_by=user.id, original_filename=filename, storage_key=key,
                              sha256=digest, size_bytes=size, created_at=stamp)
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.discard(final)
        raise
    return {**submission_view(row, queue_positions(db)), **quota_view(db, team.id, settings)}


@router.post("", status_code=202)
async def submit(request: Request, user=Depends(current_user), db=Depends(get_db)):
    """Body: the raw ZIP bytes. Header X-Filename: the URL-encoded file name."""
    await run_in_threadpool(precheck, db, user)
    filename = Path(unquote(request.headers.get("x-filename", "code.zip")).replace("\\", "/")).name[:120] or "code.zip"
    if not filename.lower().endswith(".zip"):
        raise ApiError(415, "not_zip", "ZIP 파일만 제출할 수 있습니다.")
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise ApiError(400, "bad_request", "잘못된 Content-Length입니다.")
    too_large = ApiError(413, "zip_too_large", f"ZIP 파일은 최대 {megabytes(MAX_ZIP_BYTES)}입니다.")
    if declared > MAX_ZIP_BYTES:
        raise too_large
    key = uuid.uuid4().hex
    temporary = storage.temporary_path(key)
    try:
        try:
            size, digest = await storage.receive(request.stream(), temporary, MAX_ZIP_BYTES)
        except storage.TooLarge:
            raise too_large
        if size == 0:
            raise ApiError(422, "zip_invalid", "빈 파일입니다.")
        try:
            await run_in_threadpool(zipcheck.inspect, temporary)
        except zipcheck.ZipRejected as error:
            # Refused at the door: nothing is recorded and no attempt is used.
            raise ApiError(422, "zip_invalid", str(error))
        return await run_in_threadpool(accept, db, user, filename, key, temporary, size, digest)
    finally:
        storage.discard(temporary)


@router.get("/me")
def mine(user=Depends(current_user), db=Depends(get_db)):
    """Every submission of the caller's team, newest first, with the team's remaining attempts."""
    rows = db.scalars(select(Submission).where(Submission.team_id == user.team_id).order_by(Submission.id.desc())).all()
    positions = queue_positions(db)
    names = dict(db.execute(select(User.id, User.display_name).where(User.team_id == user.team_id)).all())
    from ..files import best_public_id
    best_id = best_public_id(db, user.team_id)
    return {"entries": [{**submission_view(row, positions), "submitted_by": names.get(row.user_id),
                         "is_best_public": row.id == best_id} for row in rows],
            **quota_view(db, user.team_id, db.get(Settings, 1))}


@router.get("/{id}")
def one(id: int, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(Submission, id)
    if not row or (row.team_id != user.team_id and user.role != "ADMIN"):
        raise HTTPException(404, "제출을 찾을 수 없습니다.")
    return submission_view(row, queue_positions(db))
