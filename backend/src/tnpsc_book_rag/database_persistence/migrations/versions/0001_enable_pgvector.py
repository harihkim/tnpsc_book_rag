"""Enable the package-owned pgvector extension baseline.

Revision ID: 0001_enable_pgvector
Revises:
Created: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_enable_pgvector"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install vector types and operators in the application database."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Remove pgvector after all dependent schema revisions are downgraded."""
    op.execute("DROP EXTENSION IF EXISTS vector")
