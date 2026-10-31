"""Pages anyone can read: competition status, leaderboard, participant downloads."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from ..config import DATA_DIR
from ..dataset import MEDIA_TYPES, PUBLIC_FILES, metadata, public_metadata
from ..db import get_db
from ..leaderboard import listing
from ..models import Settings, Submission, User
from ..security import optional_user
from .common import dataset_available, evaluator_name, launched, limits_view, settings_view, submission_open
from ..config import ZIP_RETENTION

router = APIRouter(prefix="/api")


@router.get("/health")
def health(db=Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "evaluator": evaluator_name(), "dataset_ready": metadata() is not None}


@router.get("/competition")
def competition(db=Depends(get_db)):
    settings = db.get(Settings, 1)
    available = dataset_available(settings)
    # No title: it names the topic, and the web does not show it.
    return {
        "settings": settings_view(settings),
        "submission_open": submission_open(settings),
        "dataset_available": available,
        "dataset": public_metadata() if available else None,
        "limits": limits_view(settings),
        "evaluator": evaluator_name(),
        "zip_retention": ZIP_RETENTION,
        "teams": db.scalar(select(func.count(func.distinct(User.team_id))).where(User.role == "USER", User.banned.is_(False))),
        "submissions": db.scalar(select(func.count(Submission.id)).where(Submission.status == "succeeded")),
    }


@router.get("/resources/baseline")
def public_baseline(user=Depends(optional_user)):
    # Code-only archive; competition data stays behind the release gate. The code names
    # the topic, so until launch only admins get it.
    if not launched() and not (user and user.role == "ADMIN"):
        raise HTTPException(403, "베이스라인 코드는 대회 시작 후 공개됩니다.")
    path = DATA_DIR / "public/baseline_code.zip"
    if not path.exists():
        raise HTTPException(503, "베이스라인을 준비 중입니다.")
    return FileResponse(path, filename="baseline_code.zip", media_type="application/zip")


@router.get("/datasets/{kind}")
def download_dataset(kind: str):
    # No database here. FastAPI closes a request's session only after the whole file is sent,
    # so checking the release window held a pooled connection for every download; on 10-31 a
    # handful of slow downloads took all of them and every page failed. The files are served
    # whatever the schedule says; the Data tab shows the links only while `dataset_available`.
    if kind not in PUBLIC_FILES:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    path = DATA_DIR / "public" / PUBLIC_FILES[kind]
    if not path.exists():
        raise HTTPException(503, "데이터셋을 준비 중입니다.")
    return FileResponse(path, filename=PUBLIC_FILES[kind], media_type=MEDIA_TYPES[path.suffix])


@router.get("/leaderboard")
def leaderboard(board: str = "public", db=Depends(get_db)):
    if board not in {"public", "final"}:
        raise HTTPException(400, "Unknown board")
    settings = db.get(Settings, 1)
    if board == "final" and not settings.finalized:
        raise HTTPException(403, "최종 순위는 대회 종료 후 공개됩니다.")
    return {"board": board, "frozen": settings.frozen, "evaluator": evaluator_name(),
            "entries": listing(db, "private" if board == "final" else "public")}
