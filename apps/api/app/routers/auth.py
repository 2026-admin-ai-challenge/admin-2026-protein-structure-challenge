"""Login for organizer-issued accounts. There is no participant registration.

Every account signs in with its team name. Organizers can also use their own ID."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from ..accounts import team_account, team_key
from ..config import COOKIE_SECURE
from ..db import get_db
from ..models import User
from ..schemas import Login
from ..security import current_user, rate_limit, token_for, verify
from .common import user_view

router = APIRouter(prefix="/api/auth")


@router.post("/login")
def login(body: Login, request: Request, response: Response, db=Depends(get_db)):
    name = body.username.strip()
    admin = db.scalar(select(User).where(User.username == name.lower(), User.role == "ADMIN"))
    if admin:
        # Organizer IDs are never locked out of signing in.
        user = admin if verify(body.password, admin.password_hash) else None
    else:
        # The site sits behind one proxy address, so the per-address bucket is generous
        # and guessing is limited per team instead. This holds for the organizers' team
        # name too; their own ID above stays open if it runs out.
        rate_limit(db, "auth:" + request.client.host, 60)
        user = team_account(db, name, body.password)
        if not user:
            # Only a wrong password fills the team's bucket, and the right one is never
            # refused by it. Team names are public (the leaderboard lists them), so
            # counting every attempt would let anyone lock a team out of the competition
            # with ten wrong passwords a minute. Guessing is still limited to ten a minute.
            rate_limit(db, "auth-team:" + team_key(name), 10)
    if not user or user.banned:
        raise HTTPException(401, "팀 이름 또는 비밀번호를 확인하세요.")
    response.set_cookie("admin_session", token_for(user), httponly=True, secure=COOKIE_SECURE,
                        samesite="lax", max_age=43200, path="/")
    return user_view(user, db)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("admin_session", path="/")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user), db=Depends(get_db)):
    return user_view(user, db)
