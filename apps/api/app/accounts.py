"""Organizer-issued accounts: one per participant team, signed in with the team name and a
temporary password; syncing an account sheet, and deleting a team."""
import csv
import io
import secrets
import unicodedata

from sqlalchemy import delete, func, or_, select

from . import storage
from .audit import record
from .models import LeaderboardEntry, Submission, SubmissionFile, Team, User
from .reset import scoring_now
from .schemas import clean_name
from .security import DUMMY_HASH, hasher, verify

# Characters that are easy to confuse when read aloud or typed (0/o, 1/l/i) are left out.
ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
SHEET_COLUMNS = ["team_name", "password"]


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
    summary = {"name": team.name, "accounts": len(users), "submissions": len(rows), "files": len(paths)}
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


def create_user(db, team, display_name=None, password=None, role="USER"):
    """Returns (user, plaintext password). The plaintext is never stored. The username is a
    random internal value shown nowhere: the team signs in with its name."""
    password = password or random_password()
    user = User(username=unused_username(db), password_hash=hasher.hash(password),
                display_name=display_name or team.name, team_id=team.id, role=role)
    db.add(user)
    db.flush()
    return user, password


def generate_sheet(count, team_prefix="Team"):
    """CSV text with `count` teams and a temporary password for each."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(SHEET_COLUMNS)
    for index in range(1, count + 1):
        writer.writerow([f"{team_prefix} {index:02d}", random_password()])
    return out.getvalue()


def sync_sheet(db, text, exclusive=False, actor="cli"):
    """Makes the database match an account sheet (team_name, password), one row per team.

    Rows are matched to teams like sign-in names, so case and spacing do not matter. A new
    team gets its account, a changed password is updated and a blocked account listed again
    is unblocked. A name changed beyond case or spacing reads as a new team: rename teams on
    the admin page so their submissions stay with them. Teams missing from the sheet are left
    alone unless `exclusive`, which blocks every participant account the sheet does not cover.
    Organizer teams are never touched. Other columns, such as the `username` and
    `display_name` of older sheets, are ignored.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not set(SHEET_COLUMNS) <= set(reader.fieldnames):
        raise ValueError("필수 컬럼: team_name, password")
    summary = {"created": 0, "updated": 0, "unchanged": 0, "blocked": 0, "renamed_teams": 0}
    listed = set()
    rows = [(line, raw) for line, raw in enumerate(reader, start=2) if any((value or "").strip() for value in raw.values())]
    first_line = {}
    for line, raw in rows:
        try:
            team_name = clean_name(raw["team_name"] or "")
        except ValueError as error:
            raise ValueError(f"{line}행: {error}")
        password = (raw["password"] or "").strip()
        if len(password) < 8:
            raise ValueError(f"{line}행: 비밀번호는 8자 이상이어야 합니다.")
        key = team_key(team_name)
        if first_line.setdefault(key, line) != line:
            raise ValueError(f'{line}행: 팀 "{team_name}"이 {first_line[key]}행에도 있습니다. 한 팀은 한 줄로 적어 주세요(대소문자·띄어쓰기 무시).')
        if db.scalar(select(User.id).where(User.role == "ADMIN", User.username == key)):
            raise ValueError(f"{line}행: 운영진 아이디와 같은 팀 이름은 쓸 수 없습니다: {team_name}")
        team = find_team(db, team_name)
        # Unblocked first: a team that got a second account before teams had one keeps it,
        # and the sheet manages the one in use.
        members = db.scalars(select(User).where(User.team_id == team.id).order_by(User.banned, User.id)).all() if team else []
        if any(user.role == "ADMIN" for user in members):
            raise ValueError(f"{line}행: 운영진 팀은 계정 시트로 바꿀 수 없습니다: {team_name}")
        if team and team.name != team_name:
            # Only case or spacing differs: the sheet's spelling becomes the sign-in name.
            team.name = team_name
            summary["renamed_teams"] += 1
            db.flush()
        if not team:
            team = Team(name=team_name)
            db.add(team)
            db.flush()
        if not members:
            user, _ = create_user(db, team, password=password)
            listed.add(user.id)
            summary["created"] += 1
            continue
        user = members[0]
        listed.add(user.id)
        changed = False
        if user.display_name != team.name:
            user.display_name = team.name
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
            if user.id not in listed:
                user.banned = True
                summary["blocked"] += 1
    record(db, actor, "accounts.sync", "account sheet", {**summary, "exclusive": exclusive})
    return summary
