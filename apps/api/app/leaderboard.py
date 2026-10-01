from sqlalchemy import select,delete
from .models import Submission,LeaderboardEntry,User,Team

def rebuild(db,board="public"):
    field=Submission.public_score if board=="public" else Submission.private_score
    rows=db.scalars(select(Submission).join(User,User.id==Submission.user_id).where(Submission.status=="success",User.banned.is_(False)).order_by(field.desc(),Submission.created_at,Submission.id)).all()
    db.execute(delete(LeaderboardEntry).where(LeaderboardEntry.board==board))
    teams={}
    for row in rows: teams.setdefault(row.team_id,[]).append(row)
    for team_id,subs in teams.items():
        best=subs[0]
        db.add(LeaderboardEntry(team_id=team_id,submission_id=best.id,board=board,score=getattr(best,board+"_score"),achieved_at=best.created_at,submission_count=len(subs),last_submission=max(s.created_at for s in subs)))
    db.flush()

def listing(db,board):
    rows=db.execute(select(LeaderboardEntry,Team.name).join(Team,Team.id==LeaderboardEntry.team_id).join(User,User.team_id==Team.id).where(LeaderboardEntry.board==board,User.banned.is_(False)).order_by(LeaderboardEntry.score.desc(),LeaderboardEntry.achieved_at,LeaderboardEntry.submission_id)).all()
    return [{"rank":i+1,"team":name,"score":entry.score,"submissions":entry.submission_count,"last_submission":entry.last_submission} for i,(entry,name) in enumerate(rows)]
