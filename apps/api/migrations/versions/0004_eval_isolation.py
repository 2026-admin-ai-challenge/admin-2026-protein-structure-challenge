"""Whether EVALUATOR=sandbox isolates each step in a bubblewrap sandbox. On by default."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("competition_settings", sa.Column("eval_isolation", sa.Boolean, nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("competition_settings", "eval_isolation")
