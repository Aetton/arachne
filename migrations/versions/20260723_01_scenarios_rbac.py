"""versioned scenarios and composable RBAC

Revision ID: 20260723_01
Revises:
"""
from alembic import op
import sqlalchemy as sa

from database import Base

revision = "20260723_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Arachne's first migration adopts existing PoC databases as well as fresh
    # PostgreSQL installations. create_all is deliberately idempotent here.
    Base.metadata.create_all(bind=op.get_bind())
    inspector = sa.inspect(op.get_bind())
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    if "scenario_version_id" not in run_columns:
        op.add_column("runs", sa.Column("scenario_version_id", sa.Integer(), nullable=True))
    if "scenario_snapshot" not in run_columns:
        op.add_column("runs", sa.Column("scenario_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    # The adoption migration is intentionally non-destructive.
    pass
