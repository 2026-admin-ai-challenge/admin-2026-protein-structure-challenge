from sqlalchemy import delete, select

from .config import EVALUATOR
from .models import LeaderboardEntry, Submission, Team, User, utc


def _moment(row):
    """When the score was recorded. Ties go to the earlier score, then the lower ID."""
    return utc(row.finished_at or row.created_at)


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
        .where(Submission.status == "succeeded", Submission.evaluator == EVALUATOR, User.banned.is_(False))
    ).all()
    db.execute(delete(LeaderboardEntry).where(LeaderboardEntry.board == board))
    teams = {}
    for row in rows:
        teams.setdefault(row.team_id, []).append(row)
    field = "private_score" if board == "private" and selection == "best_private" else "public_score"
    for team_id, subs in teams.items():
        best = min(subs, key=lambda s: (-getattr(s, field), _moment(s), s.id))
        db.add(LeaderboardEntry(
            team_id=team_id, submission_id=best.id, board=board,
            score=best.private_score if board == "private" else best.public_score,
            achieved_at=_moment(best), submission_count=len(subs),
            last_submission=max(utc(s.created_at) for s in subs),
        ))
    db.flush()


def listing(db, board):
    rows = db.execute(
        select(LeaderboardEntry, Team.name)
        .join(Team, Team.id == LeaderboardEntry.team_id)
        .join(Submission, Submission.id == LeaderboardEntry.submission_id)
        .join(User, User.id == Submission.user_id)
        .where(LeaderboardEntry.board == board, User.banned.is_(False))
        .order_by(LeaderboardEntry.score.desc(), LeaderboardEntry.achieved_at, LeaderboardEntry.submission_id)
    ).all()
    return [
        {"rank": i + 1, "team": name, "score": entry.score, "submissions": entry.submission_count,
         "last_submission": entry.last_submission}
        for i, (entry, name) in enumerate(rows)
    ]
