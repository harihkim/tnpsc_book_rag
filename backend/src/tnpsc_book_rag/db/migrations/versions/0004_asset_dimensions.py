"""Add preserved asset dimensions, thumbnails, and accessibility metadata.

Revision ID: 0004_asset_dimensions
Revises: 0003_idempotency_records
Created: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_asset_dimensions"
down_revision: str | Sequence[str] | None = "0003_idempotency_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist intrinsic image dimensions and accessibility decisions."""
    op.add_column("assets", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("height", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("thumbnail_artifact_key", sa.Text(), nullable=True))
    op.add_column("assets", sa.Column("thumbnail_width", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("thumbnail_height", sa.Integer(), nullable=True))
    op.add_column(
        "assets",
        sa.Column(
            "accessibility_status",
            sa.String(length=20),
            server_default="unavailable",
            nullable=False,
        ),
    )
    op.add_column("assets", sa.Column("alt_text", sa.Text(), nullable=True))
    op.add_column("assets", sa.Column("alt_text_source", sa.String(length=30), nullable=True))
    op.create_check_constraint(
        op.f("ck_assets_width_positive"),
        "assets",
        "width IS NULL OR width > 0",
    )
    op.create_check_constraint(
        op.f("ck_assets_height_positive"),
        "assets",
        "height IS NULL OR height > 0",
    )
    op.create_check_constraint(
        op.f("ck_assets_thumbnail_width_positive"),
        "assets",
        "thumbnail_width IS NULL OR thumbnail_width > 0",
    )
    op.create_check_constraint(
        op.f("ck_assets_thumbnail_height_positive"),
        "assets",
        "thumbnail_height IS NULL OR thumbnail_height > 0",
    )
    op.create_check_constraint(
        op.f("ck_assets_accessibility_status"),
        "assets",
        "accessibility_status IN ('decorative', 'caption_derived', 'manual', 'unavailable')",
    )


def downgrade() -> None:
    """Remove Phase 1 asset metadata additions."""
    op.drop_constraint(op.f("ck_assets_accessibility_status"), "assets", type_="check")
    op.drop_constraint(op.f("ck_assets_thumbnail_height_positive"), "assets", type_="check")
    op.drop_constraint(op.f("ck_assets_thumbnail_width_positive"), "assets", type_="check")
    op.drop_constraint(op.f("ck_assets_height_positive"), "assets", type_="check")
    op.drop_constraint(op.f("ck_assets_width_positive"), "assets", type_="check")
    op.drop_column("assets", "alt_text_source")
    op.drop_column("assets", "alt_text")
    op.drop_column("assets", "accessibility_status")
    op.drop_column("assets", "thumbnail_height")
    op.drop_column("assets", "thumbnail_width")
    op.drop_column("assets", "thumbnail_artifact_key")
    op.drop_column("assets", "height")
    op.drop_column("assets", "width")
