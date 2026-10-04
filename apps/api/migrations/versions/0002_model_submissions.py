"""Organizer-issued accounts, team-wide limit, queued model ZIP submissions.

Existing CSV prototype submissions are kept but tagged evaluator='csv', so they never
appear on a leaderboard built from model submissions. A fresh database is recommended
for the real competition.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Accounts: login by organizer-issued ID, several accounts per team.
    op.alter_column("users", "email", new_column_name="username")
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("users"):
        if constraint["column_names"] == ["team_id"]:
            op.drop_constraint(constraint["name"], "users", type_="unique")
    op.create_index("ix_users_team_id", "users", ["team_id"])

    # Settings: whole-competition team limit and configurable undecided policies.
    op.alter_column("competition_settings", "daily_limit", new_column_name="team_submission_limit")
    op.execute("UPDATE competition_settings SET team_submission_limit = 10")
    op.add_column("competition_settings", sa.Column("count_failed", sa.Boolean, nullable=False, server_default=sa.true()))
    op.add_column("competition_settings", sa.Column("final_selection", sa.String(16), nullable=False, server_default="best_public"))
    op.add_column("competition_settings", sa.Column("dataset_version", sa.String(80)))
    op.add_column("competition_settings", sa.Column("dataset_approved_at", sa.DateTime(timezone=True)))
    op.add_column("competition_settings", sa.Column("dataset_approved_by", sa.String(254)))
    op.add_column("competition_settings", sa.Column("dataset_files", sa.Text))
    op.add_column("competition_settings", sa.Column("dataset_locked", sa.Boolean, nullable=False, server_default=sa.false()))

    # Submissions: stored ZIP, queue state, failure reason.
    op.add_column("submissions", sa.Column("failure_code", sa.String(40)))
    op.add_column("submissions", sa.Column("log_tail", sa.Text))
    op.add_column("submissions", sa.Column("storage_key", sa.String(80)))
    op.add_column("submissions", sa.Column("sha256", sa.String(64)))
    op.add_column("submissions", sa.Column("size_bytes", sa.BigInteger))
    op.add_column("submissions", sa.Column("counted", sa.Boolean, nullable=False, server_default=sa.true()))
    op.add_column("submissions", sa.Column("evaluator", sa.String(12)))
    op.add_column("submissions", sa.Column("attempts", sa.Integer, nullable=False, server_default="0"))
    op.add_column("submissions", sa.Column("worker_id", sa.String(64)))
    op.add_column("submissions", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column("submissions", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("submissions", sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE submissions SET evaluator = 'csv', finished_at = created_at")
    op.execute("UPDATE submissions SET status = 'succeeded' WHERE status = 'success'")
    op.execute("UPDATE submissions SET status = 'failed', failure_code = 'output_invalid' WHERE status = 'invalid'")
    op.create_index("ix_submissions_status", "submissions", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(254), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target", sa.String(160), nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("ok", sa.Boolean, nullable=False),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_table(
        "workers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("evaluator", sa.String(12), nullable=False),
        sa.Column("ready", sa.Boolean, nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("submission_id", sa.Integer),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    """Restores the prototype schema. Fails if any team has more than one account,
    because the old schema allowed exactly one account per team."""
    op.drop_table("workers")
    op.drop_index("ix_audit_logs_created_at", "audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_submissions_status", "submissions")
    op.execute("UPDATE submissions SET status = 'success' WHERE status = 'succeeded'")
    op.execute("UPDATE submissions SET status = 'invalid' WHERE status IN ('failed', 'queued', 'running')")
    for column in ["finished_at", "heartbeat_at", "started_at", "worker_id", "attempts", "evaluator", "counted",
                   "size_bytes", "sha256", "storage_key", "log_tail", "failure_code"]:
        op.drop_column("submissions", column)
    for column in ["dataset_locked", "dataset_files", "dataset_approved_by", "dataset_approved_at", "dataset_version",
                   "final_selection", "count_failed"]:
        op.drop_column("competition_settings", column)
    op.execute("UPDATE competition_settings SET team_submission_limit = 5")
    op.alter_column("competition_settings", "team_submission_limit", new_column_name="daily_limit")
    op.drop_index("ix_users_team_id", "users")
    op.create_unique_constraint("users_team_id_key", "users", ["team_id"])
    op.alter_column("users", "username", new_column_name="email")
