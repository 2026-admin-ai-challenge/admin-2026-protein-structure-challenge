"""Login for organizer-issued accounts. There is no participant registration."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from ..config import COOKIE_SECURE
from ..db import get_db
from ..models import User
from ..schemas import Login
from ..security import DUMMY_HASH, current_user, rate_limit, token_for, verify
from .common import user_view

router = APIRouter(prefix="/api/auth")


@router.post("/login")
def login(body: Login, request: Request, response: Response, db=Depends(get_db)):
    username = body.username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    # Organizer accounts are never locked out of signing in.
    if not user or user.role != "ADMIN":
        # The site sits behind one proxy address, so the per-address bucket is generous
        # and guessing is limited per account instead.
        rate_limit(db, "auth:" + request.client.host, 60)
        rate_limit(db, "auth-user:" + username, 10)
    valid = verify(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or user.banned:
        raise HTTPException(401, "아이디 또는 비밀번호를 확인하세요.")
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
