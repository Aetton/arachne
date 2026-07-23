"""store component metadata in the database

Revision ID: 20260723_02
Revises: 20260723_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20260723_02"
down_revision = "20260723_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "components" not in inspector.get_table_names():
        op.create_table(
            "components",
            sa.Column("slug", sa.String(length=96), primary_key=True),
            sa.Column("label", sa.String(length=160), nullable=False),
            sa.Column("icon", sa.String(length=64), nullable=False, server_default="ti-box"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # Preserve every component already referenced by a scenario. The YAML
    # bootstrap can enrich label/icon later, but the migration never drops or
    # invalidates existing scenarios.
    scenario_components = sa.table(
        "scenarios", sa.column("component", sa.String(length=96)),
    )
    components = sa.table(
        "components",
        sa.column("slug", sa.String(length=96)),
        sa.column("label", sa.String(length=160)),
        sa.column("icon", sa.String(length=64)),
        sa.column("sort_order", sa.Integer()),
    )
    slugs = [
        row[0]
        for row in bind.execute(
            sa.select(scenario_components.c.component).distinct()
        )
        if row[0]
    ]
    existing = {
        row[0] for row in bind.execute(sa.select(components.c.slug))
    }
    missing = [slug for slug in sorted(slugs) if slug not in existing]
    if missing:
        op.bulk_insert(components, [
            {
                "slug": slug,
                "label": slug.replace("-", " ").title(),
                "icon": "ti-box",
                "sort_order": index,
            }
            for index, slug in enumerate(missing)
        ])

    inspector = sa.inspect(bind)
    component_fk_exists = any(
        fk.get("referred_table") == "components"
        and fk.get("constrained_columns") == ["component"]
        for fk in inspector.get_foreign_keys("scenarios")
    )
    if not component_fk_exists:
        with op.batch_alter_table("scenarios") as batch:
            batch.create_foreign_key(
                "fk_scenarios_component_components",
                "components",
                ["component"],
                ["slug"],
                ondelete="RESTRICT",
                onupdate="CASCADE",
            )
    inspector = sa.inspect(bind)
    if not any(
        index.get("column_names") == ["component"]
        for index in inspector.get_indexes("scenarios")
    ):
        op.create_index("ix_scenarios_component", "scenarios", ["component"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if any(
        index.get("name") == "ix_scenarios_component"
        for index in inspector.get_indexes("scenarios")
    ):
        op.drop_index("ix_scenarios_component", table_name="scenarios")
    component_fk = next((
        fk for fk in inspector.get_foreign_keys("scenarios")
        if fk.get("referred_table") == "components"
        and fk.get("constrained_columns") == ["component"]
    ), None)
    if component_fk:
        # SQLite may report an unnamed FK. A naming convention gives Alembic a
        # stable synthetic name while it recreates the table in batch mode.
        constraint_name = (
            component_fk.get("name")
            or "fk_scenarios_component_components"
        )
        with op.batch_alter_table(
            "scenarios",
            naming_convention={
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            },
        ) as batch:
            batch.drop_constraint(constraint_name, type_="foreignkey")
    op.drop_table("components")
