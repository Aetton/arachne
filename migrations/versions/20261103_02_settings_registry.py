"""Typed overrides and non-secret change history."""

from alembic import op
import sqlalchemy as sa

revision = "20261103_02"
down_revision = "20261103_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "setting_overrides",
        sa.Column("key", sa.String(96), primary_key=True),
        sa.Column("value", sa.String(256), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
    )
    op.create_table(
        "setting_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(96), nullable=False),
        sa.Column("old_value", sa.String(256)),
        sa.Column("new_value", sa.String(256)),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
    )


def downgrade():
    op.drop_table("setting_changes")
    op.drop_table("setting_overrides")
