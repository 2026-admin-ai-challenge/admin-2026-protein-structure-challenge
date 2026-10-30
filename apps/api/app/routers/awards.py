"""Organizer workspace: the special awards (app/awards.py) and the winners organizers record."""
from fastapi import APIRouter, Depends, HTTPException

from .. import awards
from ..audit import record
from ..db import get_db
from ..models import Settings, SpecialAward, now
from ..schemas import AwardRecord
from ..security import admin_user
from .admin import locked_settings

router = APIRouter(prefix="/api/admin/awards")


def award_tables(settings, board, db):
    if board not in {"public", "final"}:
        raise HTTPException(400, "Unknown board")
    if board == "final" and not settings.finalized:
        raise HTTPException(409, "최종 순위를 공개한 뒤에 최종 순위로 계산할 수 있습니다.")
    return awards.tables(db, board, settings.final_selection)


@router.get("")
def special_awards(board: str = "public", admin=Depends(admin_user), db=Depends(get_db)):
    """Both award tables on the chosen board, and the winners recorded so far."""
    s = db.get(Settings, 1)
    return {"board": board, "finalized": s.finalized, "frozen": s.frozen, **award_tables(s, board, db),
            "recorded": awards.recorded(db)}


@router.post("/{kind}")
def record_award(kind: str, body: AwardRecord, admin=Depends(admin_user), db=Depends(get_db)):
    """Records a team as the winner, recomputing its row here rather than trusting the page.
    Recording again replaces the previous winner of that award."""
    if kind not in awards.KINDS:
        raise HTTPException(404, "없는 특별상입니다.")
    s = locked_settings(db)
    row = next((row for row in award_tables(s, body.board, db)[kind] if row["team_id"] == body.team_id), None)
    if row is None:
        raise HTTPException(409, "이 순위표에 없는 팀입니다. 새로 고친 뒤 다시 고르세요.")
    if kind == "climb" and row["value"] <= 0:
        raise HTTPException(409, "첫 점수 때보다 순위가 오르지 않은 팀은 기록할 수 없습니다.")
    award = db.get(SpecialAward, kind) or SpecialAward(kind=kind)
    award.board, award.team_id, award.team_name, award.value = body.board, row["team_id"], row["team"], row["value"]
    award.detail, award.recorded_by, award.recorded_at = awards.snapshot(row), admin.username, now()
    db.add(award)
    record(db, admin, "award.record", f"award:{kind}", {"team": row["team"], "board": body.board, "value": row["value"]})
    db.commit()
    return awards.record_view(award)


@router.post("/{kind}/delete")
def delete_award(kind: str, admin=Depends(admin_user), db=Depends(get_db)):
    locked_settings(db)
    award = db.get(SpecialAward, kind)
    if not award:
        raise HTTPException(404, "기록된 수상팀이 없습니다.")
    record(db, admin, "award.delete", f"award:{kind}", {"team": award.team_name, "board": award.board})
    db.delete(award)
    db.commit()
    return {"ok": True}
