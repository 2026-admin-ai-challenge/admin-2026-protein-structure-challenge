from datetime import datetime, timezone
from sqlalchemy import String,Integer,Float,Boolean,DateTime,ForeignKey,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .db import Base
def now(): return datetime.now(timezone.utc)
class Team(Base):
    __tablename__="teams"
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(60),unique=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class User(Base):
    __tablename__="users"
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(254),unique=True)
    password_hash:Mapped[str]=mapped_column(String(255))
    display_name:Mapped[str]=mapped_column(String(60))
    team_id:Mapped[int]=mapped_column(ForeignKey("teams.id"),unique=True)
    role:Mapped[str]=mapped_column(String(10),default="USER")
    banned:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Competition(Base):
    __tablename__="competitions"
    id:Mapped[int]=mapped_column(primary_key=True,default=1)
    title:Mapped[str]=mapped_column(String(160),default="ADMIN Protein Structure Classification Challenge")
class Settings(Base):
    __tablename__="competition_settings"
    id:Mapped[int]=mapped_column(ForeignKey("competitions.id"),primary_key=True,default=1)
    is_open:Mapped[bool]=mapped_column(Boolean,default=False)
    start_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    end_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    daily_limit:Mapped[int]=mapped_column(Integer,default=5)
    frozen:Mapped[bool]=mapped_column(Boolean,default=False)
    finalized:Mapped[bool]=mapped_column(Boolean,default=False)
class Submission(Base):
    __tablename__="submissions"
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    team_id:Mapped[int]=mapped_column(ForeignKey("teams.id"),index=True)
    filename:Mapped[str]=mapped_column(String(120))
    public_score:Mapped[float|None]=mapped_column(Float,nullable=True)
    private_score:Mapped[float|None]=mapped_column(Float,nullable=True)
    status:Mapped[str]=mapped_column(String(12))
    error_message:Mapped[str|None]=mapped_column(Text,nullable=True)
    predictions:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)
class LeaderboardEntry(Base):
    __tablename__="leaderboard_entries"
    __table_args__=(UniqueConstraint("team_id","board"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    team_id:Mapped[int]=mapped_column(ForeignKey("teams.id"))
    submission_id:Mapped[int]=mapped_column(ForeignKey("submissions.id"))
    board:Mapped[str]=mapped_column(String(10))
    score:Mapped[float]=mapped_column(Float)
    achieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    submission_count:Mapped[int]=mapped_column(Integer)
    last_submission:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class RateBucket(Base):
    __tablename__="rate_buckets"
    key:Mapped[str]=mapped_column(String(64),primary_key=True)
    window:Mapped[int]=mapped_column(Integer)
    count:Mapped[int]=mapped_column(Integer,default=0)
