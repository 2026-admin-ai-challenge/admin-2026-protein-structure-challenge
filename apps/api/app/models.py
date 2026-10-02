from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .config import DEFAULT_TEAM_SUBMISSION_LIMIT
from .db import Base


def now():
    return datetime.now(timezone.utc)


def utc(value):
    """SQLite returns naive datetimes; treat them as the UTC values they are."""
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    # Login ID issued by organizers. Participants cannot register.
    username: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(60))
    # Several accounts may belong to one team; limits and ranking are per team.
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="USER")
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Competition(Base):
    __tablename__ = "competitions"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    title: Mapped[str] = mapped_column(String(160), default="ADMIN Protein Structure Classification Challenge")


class Settings(Base):
    __tablename__ = "competition_settings"
    id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), primary_key=True, default=1)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Whole-competition limit per team. Never resets by date.
    team_submission_limit: Mapped[int] = mapped_column(Integer, default=DEFAULT_TEAM_SUBMISSION_LIMIT)
    # Undecided policies (Q4, Q7) stay configurable instead of being hard-coded.
    count_failed: Mapped[bool] = mapped_column(Boolean, default=True)
    final_selection: Mapped[str] = mapped_column(String(16), default="best_public")
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    # Dataset release approval: version and file hashes recorded when an organizer approves.
    dataset_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dataset_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dataset_approved_by: Mapped[str | None] = mapped_column(String(254), nullable=True)
    dataset_files: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_locked: Mapped[bool] = mapped_column(Boolean, default=False)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    filename: Mapped[str] = mapped_column(String(120))
    # queued -> running -> succeeded | failed
    status: Mapped[str] = mapped_column(String(12), index=True)
    failure_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # error_message is shown to participants. log_tail is organizer-only because container
    # output could otherwise be used to leak hidden evaluation input.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    private_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    predictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Whether this submission uses one of the team's attempts.
    counted: Mapped[bool] = mapped_column(Boolean, default=True)
    # Which evaluator produced the score, so mock results never mix with real ones.
    evaluator: Mapped[str | None] = mapped_column(String(12), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"
    __table_args__ = (UniqueConstraint("team_id", "board"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    board: Mapped[str] = mapped_column(String(10))
    score: Mapped[float] = mapped_column(Float)
    achieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submission_count: Mapped[int] = mapped_column(Integer)
    last_submission: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    """Who did what to which target, and whether it worked. Never stores passwords."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor: Mapped[str] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)


class Worker(Base):
    """Liveness and readiness reported by each scoring worker process."""
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluator: Mapped[str] = mapped_column(String(12))
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
