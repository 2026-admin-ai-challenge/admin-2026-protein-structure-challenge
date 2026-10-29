"""Interactive, server-only administrator creation or password reset; no default credentials.

    docker compose exec api python -m app.create_admin
"""
import getpass

from sqlalchemy import select

from .accounts import find_team
from .audit import record
from .db import SessionLocal
from .models import Team, User
from .schemas import clean_username
from .security import hasher

TEAM_NAME = "ADMIN organizers"


def main():
    try:
        username = clean_username(input("Admin ID: "))
    except ValueError as error:
        raise SystemExit(str(error))
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing and existing.role != "ADMIN":
            raise SystemExit("이미 참가자 계정이 쓰는 아이디입니다. 다른 아이디를 사용하세요.")
        # Participants sign in with their team name, so an organizer ID may not read as one.
        clash = None if existing else find_team(db, username)
        if clash:
            raise SystemExit(f'참가 팀 "{clash.name}"의 로그인 이름과 같은 아이디입니다. 다른 아이디를 사용하세요.')
        if existing and input("이미 있는 관리자입니다. 비밀번호를 재설정할까요? [y/N] ").strip().lower() != "y":
            raise SystemExit("취소했습니다.")
        password = getpass.getpass("Password (minimum 12 characters): ")
        if len(password) < 12:
            raise SystemExit("Password too short")
        if getpass.getpass("Confirm password: ") != password:
            raise SystemExit("Passwords differ")
        if existing:
            existing.password_hash = hasher.hash(password)
            record(db, "cli", "admin.reset_password", f"user:{username}")
        else:
            team = db.scalar(select(Team).where(Team.name == TEAM_NAME))
            if not team:
                team = Team(name=TEAM_NAME)
                db.add(team)
                db.flush()
            db.add(User(username=username, password_hash=hasher.hash(password), display_name="ADMIN", team_id=team.id, role="ADMIN"))
            record(db, "cli", "admin.create", f"user:{username}")
        db.commit()
    print("Administrator password reset" if existing else "Administrator created")


if __name__ == "__main__":
    main()
