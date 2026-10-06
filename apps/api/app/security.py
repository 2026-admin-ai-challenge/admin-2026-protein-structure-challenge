from datetime import datetime, timedelta, timezone
import hashlib
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import SECRET_KEY
from .db import get_db
from .models import RateBucket, User

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("never-a-valid-password")


def fingerprint(password_hash):
    """Ties a session to the current password, so a reset signs the account out everywhere."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def token_for(user):
    issued = datetime.now(timezone.utc)
    claims = {"sub": str(user.id), "pv": fingerprint(user.password_hash), "exp": issued + timedelta(hours=12), "iat": issued}
    return jwt.encode(claims, SECRET_KEY, algorithm="HS256")


def verify(password, hashed):
    try:
        return hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get("admin_session", "")
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        user = db.get(User, int(claims["sub"]))
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "로그인이 필요합니다.")
    if not user or user.banned:
        raise HTTPException(403, "계정에 접근할 수 없습니다.")
    if claims.get("pv") != fingerprint(user.password_hash):
        raise HTTPException(401, "비밀번호가 변경되었습니다. 다시 로그인하세요.")
    return user


def optional_user(request: Request, db=Depends(get_db)):
    """The signed-in user, or None where signing in is optional."""
    try:
        return current_user(request, db)
    except HTTPException:
        return None


def admin_user(user=Depends(current_user)):
    if user.role != "ADMIN":
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user


def rate_limit(db, key, limit=20):
    key = hashlib.sha256(key.encode()).hexdigest()
    window = int(time.time()) // 60
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(RateBucket).values(key=key, window=window, count=0).on_conflict_do_nothing(index_elements=["key"]))
    bucket = db.scalar(select(RateBucket).where(RateBucket.key == key).with_for_update())
    if bucket.window != window:
        bucket.window = window
        bucket.count = 0
    if bucket.count >= limit:
        db.commit()
        raise HTTPException(429, "요청이 너무 많습니다. 1분 후 다시 시도하세요.")
    bucket.count += 1
    db.commit()
