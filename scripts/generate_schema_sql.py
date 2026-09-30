"""Write docs/schema.sql: the PostgreSQL DDL generated from the SQLAlchemy models."""

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from songnexus.db.models import Base

OUT = Path(__file__).resolve().parents[1] / "docs" / "schema.sql"


def main() -> None:
    dialect = postgresql.dialect()
    lines = [
        "-- Generated from backend/songnexus/db/models.py for PostgreSQL 16.",
        "-- Regenerate rather than edit: python scripts/generate_schema_sql.py",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            lines.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
