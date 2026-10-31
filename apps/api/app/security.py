from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
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
from .errors import ApiError
from .models import RateBucket, User

# Each hash holds memory_cost of RAM while it runs, and the C allocator keeps what a thread
# freed for that thread. Sign-ins run on whichever of the request threads is free, so in the
# load test of 2026-10-31, 33 sign-ins at once took the API from 88 to 695 MiB and it kept
# it: the 954 MiB server could only put it in swap, and the API stalled for minutes. Two
# threads of their own do every hash instead, so at most two hashes' worth is ever held;
# the rest wait their turn, tens of milliseconds each.
HASHING_AT_ONCE = 2
_hashing = ThreadPoolExecutor(max_workers=HASHING_AT_ONCE, thread_name_prefix="argon2")


class QueuedHasher(PasswordHasher):
    """A PasswordHasher whose hashes all run on the HASHING_AT_ONCE threads of _hashing."""

    def hash(self, password, *, salt=None):
        return _hashing.submit(super().hash, password, salt=salt).result()

    def verify(self, hash, password):
        return _hashing.submit(super().verify, hash, password).result()


# Tuned for the one-OCPU web server. The library's defaults (t=3, m=64 MiB, p=4) measured
# about 2.5 s a sign-in there, because four lanes share one core, and each hash in flight
# holds 64 MiB of a 954 MiB machine. These are OWASP's recommended floor and cost about a
# fifth of the work. Parameters live inside each hash, so passwords hashed with the old
# settings still verify; sync_accounts re-hashes them (accounts.py).
hasher = QueuedHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)
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
    if not user:  # the account or its team was deleted
        raise HTTPException(401, "로그인이 필요합니다.")
    if user.banned:
        raise ApiError(403, "banned", "계정에 접근할 수 없습니다.")
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
        raise ApiError(429, "rate_limited", "요청이 너무 많습니다. 1분 후 다시 시도하세요.")
    bucket.count += 1
    db.commit()
