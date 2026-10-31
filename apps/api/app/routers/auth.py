"""Login for organizer-issued accounts. There is no participant registration.

Every account signs in with its team name. Organizers can also use their own ID.
A team can replace its password here; organizers change theirs on the server (create_admin)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from ..accounts import team_account, team_key
from ..audit import record
from ..config import COOKIE_SECURE
from ..db import get_db
from ..models import Team, User, now
from ..schemas import Login, PasswordChange
from ..security import current_user, hasher, rate_limit, token_for, verify
from .common import user_view

router = APIRouter(prefix="/api/auth")


@router.post("/login")
def login(body: Login, request: Request, response: Response, db=Depends(get_db)):
    name = body.username.strip()
    admin = db.scalar(select(User).where(User.username == name.lower(), User.role == "ADMIN"))
    if admin:
        db.commit()  # the connection goes back to the pool while the hash waits its turn
        # Organizer IDs are never locked out of signing in.
        user = admin if verify(body.password, admin.password_hash) else None
    else:
        # The site sits behind one proxy address, so every sign-in on the site shares this
        # bucket. It is sized for the whole field (about 20 teams of 3-4) signing in at the
        # start, and guessing is limited per team instead. This holds for the organizers'
        # team name too; their own ID above stays open if it runs out.
        rate_limit(db, "auth:" + request.client.host, 120)
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


@router.post("/password")
def change_password(body: PasswordChange, response: Response, user=Depends(current_user), db=Depends(get_db)):
    """A team replaces its password. Every other session of the account, teammates' included,
    is signed out; this one gets a fresh cookie."""
    if user.role == "ADMIN":
        raise HTTPException(400, "운영진 비밀번호는 서버에서 create_admin 명령으로 바꿉니다.")
    if len(body.new_password) < 8:
        raise HTTPException(422, "새 비밀번호는 8자 이상이어야 합니다.")
    if body.new_password == body.current_password:
        raise HTTPException(422, "지금과 다른 비밀번호를 입력하세요.")
    if not verify(body.current_password, user.password_hash):
        # As at sign-in, only a wrong password fills the bucket.
        rate_limit(db, f"password:{user.id}", 10)
        raise HTTPException(400, "현재 비밀번호가 맞지 않습니다.")
    user.password_hash = hasher.hash(body.new_password)
    user.password_changed_at = now()
    # The team is the actor: its account ID is internal and means nothing to organizers.
    record(db, db.get(Team, user.team_id).name, "user.change_password", f"user:{user.id}")
    db.commit()
    response.set_cookie("admin_session", token_for(user), httponly=True, secure=COOKIE_SECURE,
                        samesite="lax", max_age=43200, path="/")
    return {"ok": True}
