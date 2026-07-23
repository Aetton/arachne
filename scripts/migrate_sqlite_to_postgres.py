#!/usr/bin/env python3
"""Copy an existing Arachne SQLite database into an empty PostgreSQL database.

Usage:
  python scripts/migrate_sqlite_to_postgres.py \
    --sqlite ./data/arachne.db \
    --postgres postgresql+psycopg://arachne:secret@localhost/arachne
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from database import Base  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--postgres", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")
    source = create_engine(f"sqlite:///{sqlite_path}")
    target = create_engine(args.postgres)
    Base.metadata.create_all(target)
    target_inspector = inspect(target)
    source_inspector = inspect(source)
    source_metadata = MetaData()
    common_tables = [
        table for table in Base.metadata.sorted_tables
        if source_inspector.has_table(table.name)
        and target_inspector.has_table(table.name)
    ]
    with target.begin() as destination, source.connect() as origin:
        existing = sum(
            destination.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar_one()
            for table in common_tables
        )
        if existing:
            raise SystemExit("PostgreSQL target is not empty; refusing to duplicate data")
        for table in common_tables:
            source_table = Table(table.name, source_metadata, autoload_with=source)
            rows = origin.execute(select(source_table)).mappings().all()
            if rows:
                destination.execute(
                    table.insert(),
                    [
                        {key: value for key, value in row.items() if key in table.c}
                        for row in rows
                    ],
                )
        if target.dialect.name == "postgresql":
            for table in common_tables:
                if "id" not in table.c or not table.c.id.autoincrement:
                    continue
                destination.execute(text(
                    f"""SELECT setval(
                        pg_get_serial_sequence('"{table.name}"', 'id'),
                        COALESCE((SELECT MAX(id) FROM "{table.name}"), 1),
                        (SELECT COUNT(*) > 0 FROM "{table.name}")
                    )"""
                ))
    print(f"Migrated {len(common_tables)} tables from {sqlite_path} to PostgreSQL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
