from sqlalchemy import delete, select

from .config import EVALUATOR
from .models import LeaderboardEntry, Submission, Team, User, utc


def _moment(row):
    """When the score was recorded. Kept on the board entry for reference, not for ordering."""
    return utc(row.finished_at or row.created_at)


def _rank_key(row, score):
    """The confirmed tie rule: the higher score, then the smaller uploaded ZIP, then the
    earlier submission (lower ID). A submission without a ZIP record sorts after one with it.
    Grading time is shown for reference only and never breaks a tie."""
    size = row.size_bytes if row.size_bytes is not None else float("inf")
    return (-score, size, utc(row.created_at), row.id)


def ranked_users():
    """Accounts whose submissions may take a rank: participants that are not banned.
    Organizers' (ADMIN) test models are scored but never ranked. Applied when a board is
    built and again when it is listed, so a board stored before a ban (or before organizers
    were left out) never shows those teams."""
    return User.role == "USER", User.banned.is_(False)


def best_of(rows, field="public_score"):
    """The submission a board takes for one team, by `_rank_key` on `field`. ZIP retention
    keeps the same submission (files.py) and the board orders teams with the same key, so
    the tie rule lives only here."""
    candidates = [row for row in rows if getattr(row, field) is not None]
    return min(candidates, key=lambda s: _rank_key(s, getattr(s, field)), default=None)


def rebuild(db, board="public", selection="best_public"):
    """Rewrites one board from scored submissions.

    public: each team's best Public score.
    private (final): with selection "best_public" the Private score of that same
    submission; with "best_private" each team's best Private score.
    Submissions scored by a different evaluator (e.g. mock while running docker) are ignored.
    """
    rows = db.scalars(
        select(Submission)
        .join(User, User.id == Submission.user_id)
        .where(Submission.status == "succeeded", Submission.evaluator == EVALUATOR, *ranked_users())
    ).all()
    db.execute(delete(LeaderboardEntry).where(LeaderboardEntry.board == board))
    teams = {}
    for row in rows:
        teams.setdefault(row.team_id, []).append(row)
    field = "private_score" if board == "private" and selection == "best_private" else "public_score"
    for team_id, subs in teams.items():
        best = best_of(subs, field)
        if best is None:
            continue
        db.add(LeaderboardEntry(
            team_id=team_id, submission_id=best.id, board=board,
            score=best.private_score if board == "private" else best.public_score,
            achieved_at=_moment(best), submission_count=len(subs),
            last_submission=max(utc(s.created_at) for s in subs),
        ))
    db.flush()


def listing(db, board):
    rows = db.execute(
        select(LeaderboardEntry, Team.name, Submission)
        .join(Team, Team.id == LeaderboardEntry.team_id)
        .join(Submission, Submission.id == LeaderboardEntry.submission_id)
        .join(User, User.id == Submission.user_id)
        .where(LeaderboardEntry.board == board, *ranked_users())
    ).all()
    rows.sort(key=lambda found: _rank_key(found[2], found[0].score))
    return [
        {"rank": i + 1, "team": name, "score": entry.score, "grading_seconds": submission.grading_seconds,
         "submissions": entry.submission_count, "last_submission": entry.last_submission}
        for i, (entry, name, submission) in enumerate(rows)
    ]


def waiting(db, ranked):
    """Every other participating team, listed below the ranked ones (`listing`) by name,
    without a rank or score: no scored submission on this board yet."""
    on_board = {entry["team"] for entry in ranked}
    names = db.scalars(select(Team.name).join(User, User.team_id == Team.id).where(*ranked_users()).distinct()).all()
    return [
        {"rank": None, "team": name, "score": None, "grading_seconds": None, "submissions": 0, "last_submission": None}
        for name in sorted(names) if name not in on_board
    ]
