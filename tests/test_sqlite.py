"""The SQLite backend end to end: make, create a table, read and write rows."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from jubako.errors import BadName, DatabaseExists, DatabaseMissing, TableMissing
from jubako.fields import BOOLEAN, DATE, INTEGER, REAL, TEXT, Field
from jubako.storage import create_database, open_database

FIELDS = [
    Field("name", TEXT, "Name"),
    Field("age", INTEGER, "Age"),
    Field("weight_kg", REAL, "Weight"),
    Field("adopted_on", DATE, "Adopted on"),
    Field("is_good", BOOLEAN, "Good?"),
]


def test_create_then_reopen(sandbox: Path):
    path = sandbox / "pets.jubadb"
    with create_database(title="Pets", backend="sqlite", path=str(path)) as storage:
        assert storage.title == "Pets"
        assert storage.list_tables() == []
    assert path.exists()
    with open_database(backend="sqlite", path=str(path)) as storage:
        assert storage.describe().title == "Pets"
        assert storage.describe().backend == "sqlite"


def test_creating_twice_is_refused(sandbox: Path):
    path = str(sandbox / "pets.jubadb")
    create_database(title="Pets", backend="sqlite", path=path).close()
    with pytest.raises(DatabaseExists):
        create_database(title="Pets", backend="sqlite", path=path)


def test_opening_something_that_is_not_there(sandbox: Path):
    with pytest.raises(DatabaseMissing):
        open_database(backend="sqlite", path=str(sandbox / "nope.jubadb"))


def test_table_round_trip(database):
    database.create_table("pets", FIELDS)
    assert database.list_tables() == ["pets"]

    row_id = database.add_row(
        "pets",
        {"name": "Rex", "age": "4", "weight_kg": "12.5", "adopted_on": "2021-03-14", "is_good": "yes"},
    )
    assert row_id == 1

    page = database.list_rows("pets")
    assert page["total"] == 1
    assert page["columns"] == ["id", "name", "age", "weight_kg", "adopted_on", "is_good"]
    assert page["rows"][0][1] == "Rex"
    assert page["rows"][0][2] == 4
    assert page["rows"][0][4] == "2021-03-14"
    assert page["rows"][0][5] is True

    assert database.update_row("pets", row_id, {"age": 5}) is True
    assert database.list_rows("pets")["rows"][0][2] == 5
    assert database.delete_row("pets", row_id) is True
    assert database.count_rows("pets") == 0


def test_field_types_survive_a_reopen(sandbox: Path):
    path = str(sandbox / "pets.jubadb")
    with create_database(title="Pets", backend="sqlite", path=path) as storage:
        storage.create_table("pets", FIELDS)
    with open_database(backend="sqlite", path=path) as storage:
        info = storage.describe_table("pets")
        assert [(f.name, f.type) for f in info.fields] == [(f.name, f.type) for f in FIELDS]
        assert info.fields[3].title == "Adopted on"


def test_dates_are_stored_as_iso_text(database):
    database.create_table("pets", FIELDS)
    database.add_row("pets", {"name": "Milo", "adopted_on": dt.date(2023, 7, 1)})
    assert database.list_rows("pets")["rows"][0][4] == "2023-07-01"


def test_paging_and_sorting(database):
    database.create_table("pets", FIELDS)
    for index in range(5):
        database.add_row("pets", {"name": f"pet{index}", "age": index})
    page = database.list_rows("pets", limit=2, offset=2)
    assert [row[1] for row in page["rows"]] == ["pet2", "pet3"]
    assert page["total"] == 5
    top = database.list_rows("pets", order_by="age", descending=True, limit=1)
    assert top["rows"][0][1] == "pet4"


def test_bad_names_are_refused(database):
    with pytest.raises(BadName):
        database.create_table("pets; DROP TABLE x", FIELDS)
    with pytest.raises(BadName):
        database.create_table("pets", [Field("ok name", TEXT)])
    with pytest.raises(BadName):
        database.create_table("jubako_sneaky", FIELDS)
    database.create_table("pets", FIELDS)
    with pytest.raises(BadName):
        database.add_row("pets", {"nope": 1})
    with pytest.raises(BadName):
        database.list_rows("pets", order_by="nope")


def test_missing_table_is_reported_kindly(database):
    with pytest.raises(TableMissing):
        database.describe_table("nothing_here")


def test_internal_tables_stay_hidden(database):
    database.create_table("pets", FIELDS)
    assert database.list_tables() == ["pets"]
    assert any(name.startswith("jubako_") for name in database.real_table_names())


def test_replace_drops_the_old_table(database):
    database.create_table("pets", FIELDS)
    database.add_row("pets", {"name": "Rex"})
    database.create_table("pets", [Field("name", TEXT)], if_exists="replace")
    assert database.count_rows("pets") == 0
    assert len(database.describe_table("pets").fields) == 1


def test_a_file_that_is_not_a_database_is_a_plain_error(sandbox, capsys):
    from jubako.cli import main as cli

    junk = sandbox / "junk.jubadb"
    junk.write_text("not a database at all\n" * 50, encoding="utf-8")
    assert cli(["tables", str(junk)]) == 2
    assert "is not a database Jubako can open" in capsys.readouterr().err


def test_version_flag(capsys):
    import jubako
    from jubako.cli import main as cli

    with pytest.raises(SystemExit) as stop:
        cli(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"jubako {jubako.__version__}"
