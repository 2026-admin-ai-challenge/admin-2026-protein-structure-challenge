"""Organizer-issued accounts: random IDs, temporary passwords, and syncing an account sheet."""
import csv
import io
import secrets

from sqlalchemy import select

from .audit import record
from .models import Team, User
from .schemas import clean_name, clean_username
from .security import hasher, verify

# Characters that are easy to confuse when read aloud or typed (0/o, 1/l/i) are left out.
ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
SHEET_COLUMNS = ["team_name", "username", "password", "display_name"]


def random_id(length=10):
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(length))


def random_password(length=12):
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def unused_username(db):
    while True:
        candidate = random_id()
        if not db.scalar(select(User.id).where(User.username == candidate)):
            return candidate


def create_user(db, team, username=None, display_name=None, password=None, role="USER"):
    """Returns (user, plaintext password). The plaintext is never stored."""
    username = username or unused_username(db)
    password = password or random_password()
    user = User(username=username, password_hash=hasher.hash(password), display_name=display_name or team.name,
                team_id=team.id, role=role)
    db.add(user)
    db.flush()
    return user, password


def generate_sheet(count, team_prefix="Team"):
    """CSV text with `count` fresh accounts, one per team."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(SHEET_COLUMNS)
    seen = set()
    for index in range(1, count + 1):
        username = random_id()
        while username in seen:
            username = random_id()
        seen.add(username)
        team = f"{team_prefix} {index:02d}"
        writer.writerow([team, username, random_password(), team])
    return out.getvalue()


def sync_sheet(db, text, exclusive=False, actor="cli"):
    """Makes the database match an account sheet (team_name, username, password, display_name).

    New teams and accounts are created, changed passwords, names and teams are updated.
    Accounts missing from the sheet are left alone unless `exclusive`, which blocks every
    participant account not listed. Administrators are never touched.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"team_name", "username", "password"} <= set(reader.fieldnames):
        raise ValueError("필수 컬럼: team_name, username, password")
    summary = {"created": 0, "updated": 0, "unchanged": 0, "blocked": 0, "renamed_teams": 0}
    listed = set()
    rows = [(line, raw) for line, raw in enumerate(reader, start=2) if any((value or "").strip() for value in raw.values())]
    sheet_teams = {(raw.get("team_name") or "").strip() for _, raw in rows}
    for line, raw in rows:
        try:
            team_name = clean_name(raw["team_name"] or "")
            username = clean_username(raw["username"] or "")
            display_name = clean_name(raw.get("display_name") or team_name)
        except ValueError as error:
            raise ValueError(f"{line}행: {error}")
        password = (raw["password"] or "").strip()
        if len(password) < 8:
            raise ValueError(f"{line}행: 비밀번호는 8자 이상이어야 합니다.")
        if username in listed:
            raise ValueError(f"{line}행: 아이디가 중복되었습니다: {username}")
        listed.add(username)
        user = db.scalar(select(User).where(User.username == username))
        team = db.scalar(select(Team).where(Team.name == team_name))
        if not team and user and user.role == "USER":
            # A team name edited in the sheet renames the team, so its submissions stay with it.
            current = db.get(Team, user.team_id)
            if current.name not in sheet_teams:
                current.name = team_name
                team = current
                summary["renamed_teams"] += 1
                db.flush()
        if not team:
            team = Team(name=team_name)
            db.add(team)
            db.flush()
        if not user:
            create_user(db, team, username, display_name, password)
            summary["created"] += 1
            continue
        if user.role == "ADMIN":
            raise ValueError(f"{line}행: 관리자 계정은 계정 시트로 바꿀 수 없습니다: {username}")
        changed = False
        if user.team_id != team.id:
            user.team_id = team.id
            changed = True
        if user.display_name != display_name:
            user.display_name = display_name
            changed = True
        if user.banned:
            user.banned = False
            changed = True
        if not verify(password, user.password_hash):
            user.password_hash = hasher.hash(password)
            changed = True
        summary["updated" if changed else "unchanged"] += 1
    if exclusive:
        for user in db.scalars(select(User).where(User.role == "USER", User.banned.is_(False))):
            if user.username not in listed:
                user.banned = True
                summary["blocked"] += 1
    record(db, actor, "accounts.sync", "account sheet", {**summary, "exclusive": exclusive})
    return summary
