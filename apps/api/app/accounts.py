"""Organizer-issued accounts: team-name sign-in, temporary passwords, syncing an account
sheet, and deleting a team."""
import csv
import io
import secrets
import unicodedata

from sqlalchemy import delete, func, or_, select

from . import storage
from .audit import record
from .models import LeaderboardEntry, Submission, SubmissionFile, Team, User
from .reset import scoring_now
from .schemas import clean_name, clean_username
from .security import DUMMY_HASH, hasher, verify

# Characters that are easy to confuse when read aloud or typed (0/o, 1/l/i) are left out.
ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
SHEET_COLUMNS = ["team_name", "username", "password", "display_name"]


def random_id(length=10):
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(length))


def random_password(length=12):
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def team_key(name):
    """How team names are compared: teams sign in with their name, so case, spaces and
    Unicode form (Hangul pasted from macOS is decomposed) must not matter."""
    return unicodedata.normalize("NFKC", "".join(name.split())).casefold()


def find_team(db, name):
    key = team_key(name)
    return next((team for team in db.scalars(select(Team).order_by(Team.id)) if team_key(team.name) == key), None)


def name_conflict(db, name, team_id=None):
    """Why `name` cannot be a team name, or None. A team name is a sign-in ID, so it may not
    differ from another team's only in case or spacing, nor read as an organizer's ID."""
    other = find_team(db, name)
    if other and other.id != team_id:
        return "이미 사용 중인 팀 이름입니다."
    if db.scalar(select(User.id).where(User.role == "ADMIN", User.username == team_key(name))):
        return "운영진 아이디와 같은 팀 이름은 쓸 수 없습니다."
    return None


def team_account(db, team_name, password):
    """The account of `team_name` that `password` belongs to, or None. A team with several
    accounts tells them apart by password. Blocked accounts never match. Organizers can
    sign in this way too, with their team's name."""
    team = find_team(db, team_name)
    members = db.scalars(select(User).where(User.team_id == team.id, User.banned.is_(False))
                         .order_by(User.id)).all() if team else []
    if not members:
        verify(password, DUMMY_HASH)  # an unknown team takes as long as a wrong password
        return None
    return next((user for user in members if verify(password, user.password_hash)), None)


def remove_team(db, team):
    """Deletes a participant team for good: its accounts, submissions, file records and
    ranking entries. Returns (summary, ZIP paths to delete once committed). The caller
    holds the settings lock, records the deletion and commits."""
    users = db.scalars(select(User).where(User.team_id == team.id).order_by(User.id)).all()
    if any(user.role == "ADMIN" for user in users):
        raise ValueError("운영진 계정이 있는 팀은 삭제할 수 없습니다.")
    ids = [user.id for user in users]
    # An account moved here from another team (sheet sync) may have submitted for that team.
    elsewhere = db.scalar(select(func.count(Submission.id)).where(Submission.user_id.in_(ids), Submission.team_id != team.id))
    if elsewhere:
        raise ValueError(f"이 팀 계정이 다른 팀 소속일 때 낸 제출이 {elsewhere}건 있어 삭제할 수 없습니다. 계정을 차단하세요.")
    # Locked first, so a worker skips these rows instead of claiming one mid-deletion.
    rows = db.scalars(select(Submission).where(Submission.team_id == team.id).with_for_update()).all()
    running = scoring_now(db, team.id)
    if running:
        raise ValueError(f"채점 중인 제출이 {running}건 있습니다. 채점이 끝난 뒤 삭제하세요.")
    stored = db.scalars(select(SubmissionFile).where(
        or_(SubmissionFile.team_id == team.id, SubmissionFile.submission_id.in_([row.id for row in rows])))).all()
    paths = [storage.path_for(item.storage_key) for item in stored if not item.deleted_at]
    summary = {"name": team.name, "accounts": [user.username for user in users], "submissions": len(rows),
               "files": len(paths)}
    # Children before parents: entries and file records point at submissions, those at accounts.
    db.execute(delete(LeaderboardEntry).where(LeaderboardEntry.team_id == team.id))
    db.execute(delete(SubmissionFile).where(SubmissionFile.id.in_([item.id for item in stored])))
    db.execute(delete(Submission).where(Submission.team_id == team.id))
    db.execute(delete(User).where(User.team_id == team.id))
    db.delete(team)
    db.flush()
    return summary, paths


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
    participant account not listed. Administrators are never touched. Participants sign in
    with `team_name`; `username` only tells the accounts apart.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"team_name", "username", "password"} <= set(reader.fieldnames):
        raise ValueError("필수 컬럼: team_name, username, password")
    summary = {"created": 0, "updated": 0, "unchanged": 0, "blocked": 0, "renamed_teams": 0}
    listed = set()
    rows = [(line, raw) for line, raw in enumerate(reader, start=2) if any((value or "").strip() for value in raw.values())]
    sheet_teams = {team_key(raw.get("team_name") or "") for _, raw in rows}
    spelled = {}
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
        key = team_key(team_name)
        if spelled.setdefault(key, team_name) != team_name:
            raise ValueError(f'{line}행: 팀 이름 "{team_name}"이 다른 행의 "{spelled[key]}"와 대소문자·띄어쓰기만 다릅니다. 한 가지로 맞춰 주세요.')
        if db.scalar(select(User.id).where(User.role == "ADMIN", User.username == key)):
            raise ValueError(f"{line}행: 운영진 아이디와 같은 팀 이름은 쓸 수 없습니다: {team_name}")
        user = db.scalar(select(User).where(User.username == username))
        team = find_team(db, team_name)
        if team and team.name != team_name:
            # Only case or spacing differs: the sheet's spelling becomes the sign-in name.
            team.name = team_name
            summary["renamed_teams"] += 1
            db.flush()
        if not team and user and user.role == "USER":
            # A team name edited in the sheet renames the team, so its submissions stay with it.
            current = db.get(Team, user.team_id)
            if team_key(current.name) not in sheet_teams:
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
        if user.password_changed_at:
            # The team chose its own password, which the sheet does not know. Counted only
            # when it happens, so the summary reads as before for organizers who never see it.
            summary["team_passwords_kept"] = summary.get("team_passwords_kept", 0) + 1
        elif not verify(password, user.password_hash):
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
