"""Per-hypervisor CA bundles for TLS verification."""

from alembic import op
import sqlalchemy as sa

revision = "20261103_01"
down_revision = "20261022_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("infrastructure_connections")}
    if "ca_pem" not in cols:
        op.add_column(
            "infrastructure_connections",
            sa.Column("ca_pem", sa.Text(), nullable=False, server_default=""),
        )


def downgrade():
    op.drop_column("infrastructure_connections", "ca_pem")
