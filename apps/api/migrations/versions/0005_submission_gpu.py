"""The GPU a submission runs on, when the worker hands out GPUs (EVAL_GPU_PICK=free)."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("submissions", sa.Column("gpu", sa.String(16), nullable=True))


def downgrade():
    op.drop_column("submissions", "gpu")
