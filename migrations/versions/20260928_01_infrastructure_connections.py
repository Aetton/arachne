"""Named infrastructure connections and backend-specific template identifiers."""

from alembic import op
import sqlalchemy as sa

revision = "20260928_01"
down_revision = "20260723_02"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "infrastructure_connections" not in tables:
        op.create_table(
            "infrastructure_connections",
            sa.Column("slug", sa.String(64), primary_key=True),
            sa.Column("label", sa.String(128), nullable=False),
            sa.Column("backend", sa.String(32), nullable=False),
            sa.Column("endpoint", sa.String(512), nullable=False),
            sa.Column("credential_slug", sa.String(64), nullable=False),
            sa.Column(
                "insecure", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )
    if "golden_image_profiles" in tables:
        columns = {
            c["name"] for c in sa.inspect(bind).get_columns("golden_image_profiles")
        }
        for name in ("connection", "template_id"):
            if name not in columns:
                op.add_column(
                    "golden_image_profiles",
                    sa.Column(name, sa.String(64), nullable=True),
                )


def downgrade():
    # Removing connection identity could misroute deletion of existing machines.
    raise RuntimeError(
        "Export and remove managed infrastructure before downgrading this migration"
    )
