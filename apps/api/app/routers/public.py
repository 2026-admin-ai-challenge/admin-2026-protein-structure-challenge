"""Pages anyone can read: competition status, leaderboard, participant downloads."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from ..config import DATA_DIR
from ..dataset import MEDIA_TYPES, PUBLIC_FILES, metadata, public_metadata
from ..db import get_db
from ..leaderboard import listing
from ..models import Competition, Settings, Submission, User
from .common import dataset_available, evaluator_name, limits_view, settings_view, submission_open

router = APIRouter(prefix="/api")


@router.get("/health")
def health(db=Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "evaluator": evaluator_name(), "dataset_ready": metadata() is not None}


@router.get("/competition")
def competition(db=Depends(get_db)):
    settings = db.get(Settings, 1)
    available = dataset_available(settings)
    return {
        "title": db.get(Competition, 1).title,
        "settings": settings_view(settings),
        "submission_open": submission_open(settings),
        "dataset_available": available,
        "dataset": public_metadata() if available else None,
        "limits": limits_view(settings),
        "evaluator": evaluator_name(),
        "teams": db.scalar(select(func.count(func.distinct(User.team_id))).where(User.role == "USER", User.banned.is_(False))),
        "submissions": db.scalar(select(func.count(Submission.id)).where(Submission.status == "succeeded")),
    }


@router.get("/resources/baseline")
def public_baseline():
    # Code-only archive; competition data stays behind the release gate.
    path = DATA_DIR / "public/baseline_code.zip"
    if not path.exists():
        raise HTTPException(503, "베이스라인을 준비 중입니다.")
    return FileResponse(path, filename="baseline_code.zip", media_type="application/zip")


@router.get("/datasets/{kind}")
def download_dataset(kind: str, db=Depends(get_db)):
    if kind not in PUBLIC_FILES:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    if not dataset_available(db.get(Settings, 1)):
        raise HTTPException(403, "데이터셋은 운영진 승인 후 대회 시작부터 종료 시각까지만 공개됩니다.")
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
