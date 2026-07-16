"""Add durable mutation response replay records.

Revision ID: 0003_idempotency_records
Revises: 0002_initial_content_schema
Created: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_idempotency_records"
down_revision: str | Sequence[str] | None = "0002_initial_content_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create globally unique idempotency keys with response snapshots."""
    op.create_table(
        "idempotency_records",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "key ~ '^[A-Za-z0-9._:-]{8,128}$'",
            name=op.f("ck_idempotency_records_key_format"),
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_idempotency_records_request_sha256_format"),
        ),
        sa.CheckConstraint(
            "response_status BETWEEN 200 AND 299",
            name=op.f("ck_idempotency_records_response_status_success"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(operation)) > 0",
            name=op.f("ck_idempotency_records_operation_not_blank"),
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_idempotency_records")),
    )
    op.create_index(
        "ix_idempotency_records_expires_at",
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove mutation replay history."""
    op.drop_table("idempotency_records")
