"""Track uploaded ZIPs in their own table, linked by team_id and submission_id.

File details that lived on `submissions` (storage_key, sha256, size_bytes) move to
`submission_files`, which also records deletion. ZIP bytes stay on disk.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "submission_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("submission_id", sa.Integer, sa.ForeignKey("submissions.id"), nullable=False, unique=True),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_filename", sa.String(120), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.String(254)),
        sa.Column("delete_reason", sa.Text),
    )
    op.create_index("ix_submission_files_team_id", "submission_files", ["team_id"])
    op.execute(
        "INSERT INTO submission_files (team_id, submission_id, uploaded_by, original_filename, storage_key, sha256, size_bytes, created_at) "
        "SELECT team_id, id, user_id, filename, storage_key, sha256, size_bytes, created_at FROM submissions "
        "WHERE storage_key IS NOT NULL AND sha256 IS NOT NULL AND size_bytes IS NOT NULL"
    )
    for column in ["storage_key", "sha256", "size_bytes"]:
        op.drop_column("submissions", column)


def downgrade():
    """Puts file details back on `submissions`. Deletion records are lost."""
    op.add_column("submissions", sa.Column("storage_key", sa.String(80)))
    op.add_column("submissions", sa.Column("sha256", sa.String(64)))
    op.add_column("submissions", sa.Column("size_bytes", sa.BigInteger))
    op.execute(
        "UPDATE submissions SET storage_key = f.storage_key, sha256 = f.sha256, size_bytes = f.size_bytes "
        "FROM submission_files f WHERE f.submission_id = submissions.id AND f.deleted_at IS NULL"
    )
    op.drop_index("ix_submission_files_team_id", "submission_files")
    op.drop_table("submission_files")
