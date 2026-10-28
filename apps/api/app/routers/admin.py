"""Organizer workspace: accounts, competition settings, queue, dataset release, audit log."""
from datetime import timedelta
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .. import files, reset, storage
from ..accounts import create_user, random_password
from ..audit import record
from ..dataset import metadata, public_file_report
from ..db import get_db
from ..errors import UNCOUNTED_FAILURES
from ..leaderboard import rebuild
from ..models import AuditLog, LeaderboardEntry, Settings, Submission, SubmissionFile, Team, User, Worker, now, utc
from ..schemas import (BanPatch, CompetitionReset, CountedPatch, FileDelete, LockPatch, SettingsPatch, TeamCreate,
                       UserCreate)
from ..security import admin_user, hasher
from .common import (PENDING, admin_settings_view, evaluator_name, limits_view, queue_positions, submission_view,
                     used_attempts)

router = APIRouter(prefix="/api/admin")
WORKER_ALIVE_SECONDS = 60


def locked_settings(db):
    return db.scalar(select(Settings).where(Settings.id == 1).with_for_update())


def account_view(user):
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "role": user.role, "banned": user.banned, "created_at": user.created_at}


def admin_submission_view(row, team, user, positions=None, ranked=frozenset()):
    return {**submission_view(row, positions), "private_score": row.private_score, "team_id": row.team_id,
            "team": team, "user": user, "attempts": row.attempts, "worker_id": row.worker_id,
            "file_id": row.file.id if row.file else None, "on_leaderboard": row.id in ranked}


# ---- Overview: settings, queue, workers ---------------------------------------------------

@router.get("/overview")
def overview(admin=Depends(admin_user), db=Depends(get_db)):
    settings = db.get(Settings, 1)
    counts = dict(db.execute(select(Submission.status, func.count(Submission.id)).group_by(Submission.status)).all())
    failures = dict(db.execute(
        select(Submission.failure_code, func.count(Submission.id)).where(Submission.status == "failed").group_by(Submission.failure_code)
    ).all())
    oldest = db.scalar(select(func.min(Submission.created_at)).where(Submission.status == "queued"))
    cutoff = now() - timedelta(seconds=WORKER_ALIVE_SECONDS)
    workers = [
        {"id": w.id, "evaluator": w.evaluator, "ready": w.ready, "detail": w.detail, "submission_id": w.submission_id,
         "last_seen": w.last_seen, "alive": utc(w.last_seen) >= cutoff}
        for w in db.scalars(select(Worker).order_by(Worker.last_seen.desc()).limit(20))
    ]
    return {
        "settings": admin_settings_view(settings), "limits": limits_view(settings), "evaluator": evaluator_name(),
        "queue": {status: counts.get(status, 0) for status in ["queued", "running", "succeeded", "failed"]},
        "failures": {code or "unknown": count for code, count in failures.items()},
        "oldest_queued_at": oldest, "workers": workers,
    }


@router.patch("/competition")
def update_competition(body: SettingsPatch, admin=Depends(admin_user), db=Depends(get_db)):
    s = locked_settings(db)
    if s.finalized:
        raise HTTPException(409, "최종 순위가 이미 공개되었습니다.")
    values = body.model_dump(exclude_unset=True)
    required = ["is_open", "team_submission_limit", "count_failed", "final_selection", "frozen", "eval_isolation"]
    if any(values.get(key, "absent") is None for key in required):
        raise HTTPException(422, "설정값은 null일 수 없습니다.")
    start = values.get("start_time", s.start_time)
    end = values.get("end_time", s.end_time)
    if start and end and utc(start) >= utc(end):
        raise HTTPException(422, "종료 시간은 시작 시간 이후여야 합니다.")
    if values.get("is_open", s.is_open) and (not start or not end):
        raise HTTPException(422, "대회를 열기 전에 시작·종료 시각을 모두 설정하세요.")
    was_frozen = s.frozen
    for key, value in values.items():
        setattr(s, key, value)
    if was_frozen and not s.frozen:
        rebuild(db)
    record(db, admin, "settings.update", "competition", values)
    db.commit()
    return admin_settings_view(s)


@router.post("/competition/reset")
def reset_competition(body: CompetitionReset, admin=Depends(admin_user), db=Depends(get_db)):
    """Deletes submissions, ZIPs, rankings and the audit log for good, for the next competition.
    Accounts and teams stay. The reset itself becomes the first entry of the new audit log."""
    if body.confirm.strip() != reset.CONFIRM_PHRASE:
        raise HTTPException(422, f'확인 문구 "{reset.CONFIRM_PHRASE}"를 정확히 입력하세요.')
    s = locked_settings(db)
    if s.is_open:
        raise HTTPException(409, "먼저 대회를 닫아 주세요.")
    running = reset.scoring_now(db)
    if running:
        raise HTTPException(409, f"채점 중인 제출이 {running}건 있습니다. 채점이 끝난 뒤 초기화하세요.")
    summary = reset.clear(db, s)
    record(db, admin, "competition.reset", "competition", summary)
    db.commit()
    # After the commit: a ZIP that cannot be deleted stays on disk, and the file check reports it.
    not_deleted = reset.delete_files()
    if not_deleted:
        record(db, admin, "competition.reset", "files", {"not_deleted": not_deleted}, ok=False)
        db.commit()
    return {**summary, "not_deleted": not_deleted, "settings": admin_settings_view(s)}


# ---- Teams and accounts -------------------------------------------------------------------

@router.get("/teams")
def teams(admin=Depends(admin_user), db=Depends(get_db)):
    settings = db.get(Settings, 1)
    users = {}
    for user in db.scalars(select(User).order_by(User.id)):
        users.setdefault(user.team_id, []).append(account_view(user))
    used = dict(db.execute(
        select(Submission.team_id, func.count(Submission.id)).where(Submission.counted.is_(True)).group_by(Submission.team_id)
    ).all())
    total = dict(db.execute(select(Submission.team_id, func.count(Submission.id)).group_by(Submission.team_id)).all())
    best = dict(db.execute(select(LeaderboardEntry.team_id, LeaderboardEntry.score).where(LeaderboardEntry.board == "public")).all())
    usage = files.usage_by_team(db)
    return [
        {"id": team.id, "name": team.name, "created_at": team.created_at, "users": users.get(team.id, []),
         "used": used.get(team.id, 0), "limit": settings.team_submission_limit,
         "submissions": total.get(team.id, 0), "best_public": best.get(team.id),
         "files": usage.get(team.id, (0, 0))[0], "storage_bytes": usage.get(team.id, (0, 0))[1]}
        for team in db.scalars(select(Team).order_by(Team.id))
    ]


@router.post("/teams", status_code=201)
def create_team(body: TeamCreate, admin=Depends(admin_user), db=Depends(get_db)):
    team = Team(name=body.name)
    db.add(team)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "이미 사용 중인 팀 이름입니다.")
    record(db, admin, "team.create", f"team:{team.id}", {"name": team.name})
    db.commit()
    return {"id": team.id, "name": team.name}


@router.patch("/teams/{id}")
def rename_team(id: int, body: TeamCreate, admin=Depends(admin_user), db=Depends(get_db)):
    team = db.get(Team, id)
    if not team:
        raise HTTPException(404, "팀이 없습니다.")
    previous, team.name = team.name, body.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "이미 사용 중인 팀 이름입니다.")
    record(db, admin, "team.rename", f"team:{team.id}", {"from": previous, "to": team.name})
    db.commit()
    return {"id": team.id, "name": team.name}


@router.post("/users", status_code=201)
def issue_account(body: UserCreate, admin=Depends(admin_user), db=Depends(get_db)):
    """Creates a participant account. The temporary password is returned once and only its hash is stored."""
    team = db.get(Team, body.team_id)
    if not team:
        raise HTTPException(404, "팀이 없습니다.")
    try:
        user, password = create_user(db, team, body.username, body.display_name)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "이미 사용 중인 아이디입니다.")
    record(db, admin, "user.create", f"user:{user.username}", {"team": team.name})
    db.commit()
    return {**account_view(user), "team_id": team.id, "team_name": team.name, "temporary_password": password}


@router.post("/users/{id}/reset-password")
def reset_password(id: int, admin=Depends(admin_user), db=Depends(get_db)):
    user = db.get(User, id)
    if not user:
        raise HTTPException(404, "사용자가 없습니다.")
    if user.role == "ADMIN":
        raise HTTPException(400, "관리자 비밀번호는 서버에서 create_admin 명령으로 재설정합니다.")
    password = random_password()
    user.password_hash = hasher.hash(password)  # also signs the account out everywhere
    record(db, admin, "user.reset_password", f"user:{user.username}")
    db.commit()
    return {**account_view(user), "temporary_password": password}


@router.patch("/users/{id}")
def ban(id: int, body: BanPatch, admin=Depends(admin_user), db=Depends(get_db)):
    s = locked_settings(db)
    if s.finalized:
        raise HTTPException(409, "최종 순위 공개 후에는 계정 상태를 변경할 수 없습니다.")
    user = db.get(User, id)
    if not user:
        raise HTTPException(404, "사용자가 없습니다.")
    if user.role == "ADMIN":
        raise HTTPException(400, "관리자 계정은 차단할 수 없습니다.")
    user.banned = body.banned
    db.flush()
    if not s.frozen:
        rebuild(db)
    record(db, admin, "user.ban" if body.banned else "user.unban", f"user:{user.username}")
    db.commit()
    return {"ok": True}


# ---- Submissions and queue ----------------------------------------------------------------

def submission_query():
    return (select(Submission, Team.name, User.username)
            .join(Team, Team.id == Submission.team_id).join(User, User.id == Submission.user_id))


@router.get("/submissions")
def all_submissions(status: str | None = None, failure_code: str | None = None, team_id: int | None = None,
                    q: str | None = None, limit: int = 200, admin=Depends(admin_user), db=Depends(get_db)):
    query = submission_query()
    if status:
        query = query.where(Submission.status == status)
    if failure_code:
        query = query.where(Submission.failure_code == failure_code)
    if team_id:
        query = query.where(Submission.team_id == team_id)
    if q and q.strip():
        term = q.strip()
        conditions = [Team.name.ilike(f"%{term}%"), Submission.filename.ilike(f"%{term}%"), User.username.ilike(f"%{term}%")]
        if term.isdigit():
            conditions.append(Submission.id == int(term))
        query = query.where(or_(*conditions))
    positions, ranked = queue_positions(db), files.ranked_submission_ids(db)
    rows = db.execute(query.order_by(Submission.id.desc()).limit(max(1, min(limit, 1000)))).all()
    return [admin_submission_view(row, team, user, positions, ranked) for row, team, user in rows]


@router.get("/submissions/{id}")
def submission_detail(id: int, admin=Depends(admin_user), db=Depends(get_db)):
    found = db.execute(submission_query().where(Submission.id == id)).first()
    if not found:
        raise HTTPException(404, "제출을 찾을 수 없습니다.")
    row, team, user = found
    detail = admin_submission_view(row, team, user, queue_positions(db), files.ranked_submission_ids(db))
    stored = row.file
    return {**detail, "log_tail": row.log_tail,
            "file_present": bool(row.storage_key) and storage.path_for(row.storage_key).exists(),
            "file_deleted_at": stored.deleted_at if stored else None,
            "file_deleted_by": stored.deleted_by if stored else None,
            "file_delete_reason": stored.delete_reason if stored else None}


@router.post("/submissions/{id}/requeue")
def requeue(id: int, admin=Depends(admin_user), db=Depends(get_db)):
    """Scores a failed submission again, e.g. after a server fault. Uses the stored ZIP."""
    s = locked_settings(db)
    if s.finalized:
        raise HTTPException(409, "최종 순위 공개 후에는 다시 채점할 수 없습니다.")
    row = db.scalar(select(Submission).where(Submission.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "제출을 찾을 수 없습니다.")
    if row.status != "failed":
        raise HTTPException(409, "실패한 제출만 다시 채점할 수 있습니다.")
    if not row.storage_key or not storage.path_for(row.storage_key).exists():
        raise HTTPException(409, "저장된 ZIP이 없어 다시 채점할 수 없습니다.")
    previous = row.failure_code
    # An attempt the system gave back by itself (server fault, ZIP violation, or every
    # failure while count_failed is off) is used again, like a fresh submission. One an
    # organizer refunded by hand stays refunded. The team limit is not checked here.
    if previous in UNCOUNTED_FAILURES or not s.count_failed:
        row.counted = True
    row.status, row.attempts, row.worker_id = "queued", 0, None
    row.failure_code = row.error_message = row.log_tail = None
    row.started_at = row.heartbeat_at = row.finished_at = None
    record(db, admin, "submission.requeue", f"submission:{row.id}", {"previous_failure": previous})
    db.commit()
    return {"ok": True}


@router.patch("/submissions/{id}")
def set_counted(id: int, body: CountedPatch, admin=Depends(admin_user), db=Depends(get_db)):
    """Gives an attempt back to a team (or takes it again)."""
    row = db.scalar(select(Submission).where(Submission.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "제출을 찾을 수 없습니다.")
    row.counted = body.counted
    db.flush()
    record(db, admin, "submission.counted", f"submission:{row.id}", {"counted": body.counted})
    db.commit()
    return {"ok": True, "used": used_attempts(db, row.team_id)}


# ---- Stored submission files --------------------------------------------------------------

@router.get("/files")
def list_files(team_id: int | None = None, limit: int = 500, admin=Depends(admin_user), db=Depends(get_db)):
    """Every uploaded ZIP with its owner team, plus how much each team is storing."""
    query = (select(SubmissionFile, Team.name, User.username, Submission.status, Submission.public_score)
             .join(Team, Team.id == SubmissionFile.team_id).join(User, User.id == SubmissionFile.uploaded_by)
             .join(Submission, Submission.id == SubmissionFile.submission_id))
    if team_id:
        query = query.where(SubmissionFile.team_id == team_id)
    ranked = files.ranked_submission_ids(db)
    rows = db.execute(query.order_by(SubmissionFile.id.desc()).limit(max(1, min(limit, 2000)))).all()
    usage = files.usage_by_team(db)
    names = dict(db.execute(select(Team.id, Team.name)).all())
    return {
        "files": [
            {"id": f.id, "team_id": f.team_id, "team": team, "submission_id": f.submission_id, "uploaded_by": username,
             "original_filename": f.original_filename, "sha256": f.sha256, "size_bytes": f.size_bytes,
             "created_at": f.created_at, "deleted_at": f.deleted_at, "deleted_by": f.deleted_by,
             "delete_reason": f.delete_reason, "status": status, "public_score": score,
             "on_leaderboard": f.submission_id in ranked}
            for f, team, username, status, score in rows
        ],
        "teams": [{"team_id": id, "team": names.get(id), "files": count, "storage_bytes": total}
                  for id, (count, total) in sorted(usage.items())],
        "total_bytes": sum(total for _, total in usage.values()),
    }


@router.get("/files/{id}/download")
def download_file(id: int, admin=Depends(admin_user), db=Depends(get_db)):
    """The stored ZIP, for reproduction review. Organizers only; every download is logged."""
    stored = db.get(SubmissionFile, id)
    if not stored:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    if stored.deleted_at:
        raise HTTPException(410, "삭제된 파일입니다.")
    path = storage.path_for(stored.storage_key)
    if not path.exists():
        raise HTTPException(409, "저장된 ZIP이 디스크에 없습니다. 파일 정합성 검사를 실행하세요.")
    record(db, admin, "file.download", f"file:{stored.id}", {"submission": stored.submission_id, "team_id": stored.team_id})
    db.commit()
    name = f"team{stored.team_id}-submission{stored.submission_id}-{stored.original_filename}"
    return FileResponse(path, filename=name, media_type="application/zip")


@router.post("/files/{id}/delete")
def delete_file(id: int, body: FileDelete, admin=Depends(admin_user), db=Depends(get_db)):
    """Removes the ZIP from disk and keeps the record with who, when and why."""
    stored = db.scalar(select(SubmissionFile).where(SubmissionFile.id == id).with_for_update())
    if not stored:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    if stored.deleted_at:
        raise HTTPException(409, "이미 삭제된 파일입니다.")
    submission = db.get(Submission, stored.submission_id)
    if submission.status in PENDING:
        raise HTTPException(409, "채점이 끝나지 않은 제출의 파일은 삭제할 수 없습니다.")
    if stored.submission_id in files.ranked_submission_ids(db):
        raise HTTPException(409, "순위에 반영된 제출의 파일은 삭제할 수 없습니다.")
    try:
        storage.discard(storage.path_for(stored.storage_key))
    except OSError as error:
        raise HTTPException(500, f"파일을 삭제하지 못했습니다: {error}")
    stored.deleted_at, stored.deleted_by, stored.delete_reason = now(), admin.username, body.reason
    record(db, admin, "file.delete", f"file:{stored.id}",
           {"submission": stored.submission_id, "team_id": stored.team_id, "reason": body.reason})
    db.commit()
    return {"ok": True}


@router.post("/files/verify")
def verify_files(admin=Depends(admin_user), db=Depends(get_db)):
    """Compares records with the disk (presence and size). Changes nothing."""
    report = files.check(db)
    summary = {key: len(value) if isinstance(value, list) else value for key, value in report.items()}
    record(db, admin, "file.verify", "submission files", summary, ok=report["ok"])
    db.commit()
    return report


# ---- Leaderboard --------------------------------------------------------------------------

@router.post("/leaderboard/recalculate")
def recalculate(admin=Depends(admin_user), db=Depends(get_db)):
    """Rebuilds the Public ranking from stored scores. Re-scoring against labels is a worker command."""
    s = locked_settings(db)
    if s.finalized or s.frozen:
        raise HTTPException(409, "순위 동결을 해제한 후 재계산하세요. 최종 공개 후에는 변경할 수 없습니다.")
    rebuild(db)
    record(db, admin, "leaderboard.recalculate", "leaderboard:public")
    db.commit()
    return {"ok": True}


@router.post("/leaderboard/finalize")
def finalize(admin=Depends(admin_user), db=Depends(get_db)):
    s = locked_settings(db)
    if s.finalized:
        return {"ok": True}
    if s.is_open:
        raise HTTPException(409, "먼저 대회를 닫아 주세요.")
    pending = db.scalar(select(func.count(Submission.id)).where(Submission.status.in_(PENDING)))
    if pending:
        raise HTTPException(409, f"채점이 끝나지 않은 제출이 {pending}건 있습니다. 대기열이 비워진 뒤 공개하세요.")
    rebuild(db)
    rebuild(db, "private", s.final_selection)
    s.finalized = True
    s.frozen = True
    record(db, admin, "leaderboard.finalize", "leaderboard:final", {"final_selection": s.final_selection})
    db.commit()
    return {"ok": True}


# ---- Dataset release ----------------------------------------------------------------------

def dataset_view(settings):
    meta = metadata()
    approved = json.loads(settings.dataset_files) if settings.dataset_files else {}
    files = public_file_report()
    for entry in files:
        entry["approved_sha256"] = approved.get(entry["name"])
    return {
        "metadata_present": meta is not None,
        # PROVISIONAL: `version` and `validation` are read from metadata.json when the data team provides them.
        "version": (meta or {}).get("version"),
        "validation": (meta or {}).get("validation"),
        "stats": (meta or {}).get("stats"),
        "files": files,
        "approved": {"version": settings.dataset_version, "at": settings.dataset_approved_at,
                     "by": settings.dataset_approved_by, "locked": settings.dataset_locked},
    }


@router.get("/dataset")
def dataset(admin=Depends(admin_user), db=Depends(get_db)):
    return dataset_view(db.get(Settings, 1))


@router.post("/dataset/approve")
def approve_dataset(admin=Depends(admin_user), db=Depends(get_db)):
    """Records the version and SHA-256 of every participant file, which opens downloads during the competition."""
    s = locked_settings(db)
    if s.dataset_locked:
        raise HTTPException(409, "데이터 버전이 잠겨 있습니다. 잠금을 해제한 뒤 다시 승인하세요.")
    meta = metadata()
    if not meta:
        raise HTTPException(409, "데이터 저장소의 metadata.json이 없습니다. 데이터팀이 준비한 디렉터리를 연결하세요.")
    hashes = {entry["name"]: entry["sha256"] for entry in public_file_report(with_hashes=True) if entry["present"]}
    if "train.csv" not in hashes:
        raise HTTPException(409, "학습 데이터(train.csv)가 없습니다.")
    s.dataset_version = str(meta.get("version") or "unversioned")[:80]
    s.dataset_files = json.dumps(hashes)
    s.dataset_approved_at = now()
    s.dataset_approved_by = admin.username
    record(db, admin, "dataset.approve", f"dataset:{s.dataset_version}", {"files": len(hashes)})
    db.commit()
    return dataset_view(s)


@router.post("/dataset/verify")
def verify_dataset(admin=Depends(admin_user), db=Depends(get_db)):
    """Re-hashes the files and reports any that differ from what was approved."""
    s = db.get(Settings, 1)
    if not s.dataset_files:
        raise HTTPException(409, "승인된 데이터 버전이 없습니다.")
    approved = json.loads(s.dataset_files)
    current = {entry["name"]: entry["sha256"] for entry in public_file_report(with_hashes=True) if entry["present"]}
    changed = sorted(name for name in set(approved) | set(current) if approved.get(name) != current.get(name))
    record(db, admin, "dataset.verify", f"dataset:{s.dataset_version}", {"changed": changed}, ok=not changed)
    db.commit()
    return {"ok": not changed, "changed": changed}


@router.post("/dataset/lock")
def lock_dataset(body: LockPatch, admin=Depends(admin_user), db=Depends(get_db)):
    s = locked_settings(db)
    if body.locked and not s.dataset_version:
        raise HTTPException(409, "먼저 데이터 버전을 승인하세요.")
    if not body.locked and s.is_open:
        raise HTTPException(409, "대회가 열려 있는 동안에는 잠금을 해제할 수 없습니다.")
    s.dataset_locked = body.locked
    record(db, admin, "dataset.lock" if body.locked else "dataset.unlock", f"dataset:{s.dataset_version}")
    db.commit()
    return dataset_view(s)


# ---- Audit log ----------------------------------------------------------------------------

@router.get("/audit")
def audit(limit: int = 100, admin=Depends(admin_user), db=Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500))))
    return [{"id": r.id, "created_at": r.created_at, "actor": r.actor, "action": r.action, "target": r.target,
             "detail": r.detail, "ok": r.ok} for r in rows]
