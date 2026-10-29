"""The special award winners organizers record on the admin page."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "special_awards",
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.Column("board", sa.String(10), nullable=False),
        sa.Column("team_id", sa.Integer, nullable=False),
        sa.Column("team_name", sa.String(60), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("recorded_by", sa.String(254), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("special_awards")
