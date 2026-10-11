#!/usr/bin/env python3
"""Prove a server backend works, against a real PostgreSQL or MySQL server.

This is a smoke test, not a unit test: it needs a server you can reach, so it
lives here rather than in `tests/`. Point it at a database you do not mind it
writing to — it creates a table, lists it, adds a row, reads it back and then
drops the table again.

    # PostgreSQL
    python scripts/smoke_remote.py postgres \
        --host localhost --port 5432 --database jubako_smoke --user postgres --password secret

    # MySQL / MariaDB
    python scripts/smoke_remote.py mysql \
        --host 127.0.0.1 --port 3306 --database jubako_smoke --user root --password secret

Connection details can also come from the environment, so nothing has to be
typed on a shared command line:

    JUBAKO_PG_URL=postgresql://user:pw@localhost/jubako_smoke python scripts/smoke_remote.py postgres
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jubako.errors import JubakoError  # noqa: E402
from jubako.fields import BOOLEAN, DATE, INTEGER, REAL, TEXT, Field  # noqa: E402
from jubako.storage import create_database, open_database  # noqa: E402

TABLE = "smoke_pets"  # not "jubako_...": that prefix is kept for Jubako's own tables

FIELDS = [
    Field("name", TEXT, "Name"),
    Field("age", INTEGER, "Age"),
    Field("weight_kg", REAL, "Weight"),
    Field("adopted_on", DATE, "Adopted on"),
    Field("is_good", BOOLEAN, "Good?"),
]


def step(text: str) -> None:
    print(f"  .. {text}")


def run(backend: str, connection: dict) -> int:
    print(f"Jubako smoke test: {backend}")

    step("connecting and setting up Jubako's own tables")
    storage = create_database(title="Smoke test", backend=backend, connection=connection)
    print(f"     connected to {storage.location()}")

    try:
        step(f"creating an empty table {TABLE!r}")
        storage.create_table(TABLE, FIELDS, if_exists="replace")

        step("listing tables")
        tables = storage.list_tables()
        assert TABLE in tables, f"{TABLE} missing from {tables}"
        print(f"     tables: {tables}")

        step("describing the table")
        info = storage.describe_table(TABLE)
        types = [(f.name, f.type) for f in info.fields]
        assert types == [(f.name, f.type) for f in FIELDS], types
        print(f"     fields: {types}")

        step("adding a row and reading it back")
        row_id = storage.add_row(
            TABLE,
            {
                "name": "Rex",
                "age": "4",
                "weight_kg": "12.5",
                "adopted_on": "2021-03-14",
                "is_good": "yes",
            },
        )
        page = storage.list_rows(TABLE)
        assert page["total"] == 1, page
        row = page["rows"][0]
        assert row[1] == "Rex" and row[2] == 4 and row[5] is True, row
        print(f"     row {row_id}: {row}")

        step("updating and deleting the row")
        assert storage.update_row(TABLE, row_id, {"age": 5})
        assert storage.list_rows(TABLE)["rows"][0][2] == 5
        assert storage.delete_row(TABLE, row_id)
        assert storage.count_rows(TABLE) == 0
    finally:
        step("cleaning up")
        try:
            storage.drop_table(TABLE)
        finally:
            storage.close()

    step("reopening to be sure it persisted")
    reopened = open_database(backend=backend, connection=connection)
    try:
        assert TABLE not in reopened.list_tables()
        print(f"     title: {reopened.describe().title!r}")
    finally:
        reopened.close()

    print(f"OK — {backend} works end to end.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=["postgres", "mysql"])
    parser.add_argument("--host", default=os.environ.get("JUBAKO_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--database", default=os.environ.get("JUBAKO_NAME", "jubako_smoke"))
    parser.add_argument("--user", default=os.environ.get("JUBAKO_USER", ""))
    parser.add_argument(
        "--password",
        default=os.environ.get("JUBAKO_PASSWORD", ""),
        help="Better given through JUBAKO_PASSWORD than typed here.",
    )
    parser.add_argument("--url", default=os.environ.get("JUBAKO_PG_URL", ""))
    args = parser.parse_args(argv)

    if args.backend == "postgres":
        connection = (
            {"url": args.url}
            if args.url
            else {
                "host": args.host,
                "port": args.port or 5432,
                "database": args.database,
                "user": args.user,
                "password": args.password,
            }
        )
    else:
        connection = {
            "host": args.host,
            "port": args.port or 3306,
            "database": args.database,
            "user": args.user,
            "password": args.password,
        }

    try:
        return run(args.backend, connection)
    except JubakoError as error:
        print(f"FAILED — {error}", file=sys.stderr)
        return 2
    except AssertionError as error:
        print(f"FAILED — {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
