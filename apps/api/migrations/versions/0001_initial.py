"""Initial competition schema."""
from alembic import op
import sqlalchemy as sa
revision="0001"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("teams",sa.Column("id",sa.Integer,primary_key=True),sa.Column("name",sa.String(60),nullable=False,unique=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("users",sa.Column("id",sa.Integer,primary_key=True),sa.Column("email",sa.String(254),nullable=False,unique=True),sa.Column("password_hash",sa.String(255),nullable=False),sa.Column("display_name",sa.String(60),nullable=False),sa.Column("team_id",sa.Integer,sa.ForeignKey("teams.id"),nullable=False,unique=True),sa.Column("role",sa.String(10),nullable=False),sa.Column("banned",sa.Boolean,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("competitions",sa.Column("id",sa.Integer,primary_key=True),sa.Column("title",sa.String(160),nullable=False))
    op.create_table("competition_settings",sa.Column("id",sa.Integer,sa.ForeignKey("competitions.id"),primary_key=True),sa.Column("is_open",sa.Boolean,nullable=False),sa.Column("start_time",sa.DateTime(timezone=True)),sa.Column("end_time",sa.DateTime(timezone=True)),sa.Column("daily_limit",sa.Integer,nullable=False),sa.Column("frozen",sa.Boolean,nullable=False),sa.Column("finalized",sa.Boolean,nullable=False))
    op.create_table("submissions",sa.Column("id",sa.Integer,primary_key=True),sa.Column("user_id",sa.Integer,sa.ForeignKey("users.id"),nullable=False),sa.Column("team_id",sa.Integer,sa.ForeignKey("teams.id"),nullable=False),sa.Column("filename",sa.String(120),nullable=False),sa.Column("public_score",sa.Float),sa.Column("private_score",sa.Float),sa.Column("status",sa.String(12),nullable=False),sa.Column("error_message",sa.Text),sa.Column("predictions",sa.Text),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    for field in ["user_id","team_id","created_at"]: op.create_index("ix_submissions_"+field,"submissions",[field])
    op.create_table("leaderboard_entries",sa.Column("id",sa.Integer,primary_key=True),sa.Column("team_id",sa.Integer,sa.ForeignKey("teams.id"),nullable=False),sa.Column("submission_id",sa.Integer,sa.ForeignKey("submissions.id"),nullable=False),sa.Column("board",sa.String(10),nullable=False),sa.Column("score",sa.Float,nullable=False),sa.Column("achieved_at",sa.DateTime(timezone=True),nullable=False),sa.Column("submission_count",sa.Integer,nullable=False),sa.Column("last_submission",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("team_id","board"))
    op.create_table("rate_buckets",sa.Column("key",sa.String(64),primary_key=True),sa.Column("window",sa.Integer,nullable=False),sa.Column("count",sa.Integer,nullable=False))
def downgrade():
    for table in ["rate_buckets","leaderboard_entries","submissions","competition_settings","competitions","users","teams"]: op.drop_table(table)
