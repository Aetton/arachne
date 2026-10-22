"""Nested groups and persistent scenario ordering."""
from alembic import op
import sqlalchemy as sa

revision = "20261022_01"
down_revision = "20260928_01"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    # The adoption migration creates current metadata on a fresh installation.
    if "parent_group" not in {c["name"] for c in inspector.get_columns("components")}:
        with op.batch_alter_table("components") as batch:
            batch.add_column(sa.Column("parent_group", sa.String(96), nullable=True))
            batch.create_foreign_key("fk_component_parent", "components", ["parent_group"], ["slug"], ondelete="RESTRICT")
            batch.create_index("ix_components_parent_group", ["parent_group"])
    if "sort_order" not in {c["name"] for c in inspector.get_columns("scenarios")}:
        with op.batch_alter_table("scenarios") as batch:
            batch.add_column(sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("scenarios") as batch:
        batch.drop_column("sort_order")
    with op.batch_alter_table("components") as batch:
        batch.drop_index("ix_components_parent_group")
        batch.drop_constraint("fk_component_parent", type_="foreignkey")
        batch.drop_column("parent_group")
