"""Keys: no-repeats (unique) fields, and giving a table made elsewhere a row number."""

from __future__ import annotations

import sqlite3

import pytest

from jubako import schema
from jubako.errors import JubakoError
from jubako.fields import Field
from jubako.storage import open_database


@pytest.fixture
def people(database):
    database.create_table("people", [Field("name"), Field("email"), Field("member", "boolean")])
    for name, email in [("Ann", "ann@example.com"), ("Bo", "bo@example.com"), ("Cy", None), ("Di", None)]:
        database.add_row("people", {"name": name, "email": email})
    return database


def test_a_field_can_be_made_no_repeats_and_blanks_may_still_repeat(people):
    result = schema.set_unique(people, "people", "email", True)
    assert {"name": "email", "type": "text", "label": "Email", "unique": True} in result["fields"]
    assert people.describe_table("people").fields[1].unique is True
    with pytest.raises(JubakoError, match="Email cannot repeat: “ann@example.com” is already in another row"):
        people.add_row("people", {"name": "Ann again", "email": "ann@example.com"})
    people.add_row("people", {"name": "Ed"})                   # a third blank is fine
    ids = [row[0] for row in people.list_rows("people")["rows"]]
    with pytest.raises(JubakoError, match="cannot repeat"):
        people.update_row("people", ids[1], {"email": "ann@example.com"})
    assert people.update_row("people", ids[0], {"email": "ann@example.com", "name": "Ann"}) is True  # its own value
    assert people.count_rows("people") == 5


def test_no_repeats_is_refused_while_values_repeat(people):
    schema.set_unique(people, "people", "name", True)
    schema.set_unique(people, "people", "name", False)
    people.add_row("people", {"name": "Ann"})
    with pytest.raises(JubakoError, match="Name already repeats.*“Ann” \\(2 rows\\)"):
        schema.set_unique(people, "people", "name", True)
    with pytest.raises(JubakoError, match="only has two values"):
        schema.set_unique(people, "people", "member", True)
    assert people.repeated_values("people", "name") == [("Ann", 2)]


def test_no_repeats_follows_renames_drops_and_new_fields(people):
    schema.set_unique(people, "people", "email", True)
    schema.rename_field(people, "people", "email", "mail")
    with pytest.raises(JubakoError, match="cannot repeat"):
        people.add_row("people", {"name": "X", "mail": "bo@example.com"})
    # SQLite refuses to drop an indexed column; the index goes first.
    schema.drop_field(people, "people", "mail")
    assert [f.name for f in people.describe_table("people").fields] == ["name", "member"]
    added = schema.add_field(people, "people", label="Code", field_type="integer", unique=True)
    assert added["fields"][-1]["unique"] is True
    people.add_row("people", {"name": "Y", "code": 7})
    with pytest.raises(JubakoError, match="Code cannot repeat: “7”"):
        people.add_row("people", {"name": "Z", "code": "7"})


def test_no_repeats_survives_closing_the_database(sandbox):
    from jubako.storage import create_database

    path = str(sandbox / "keep.jubadb")
    with create_database(title="Keep", backend="sqlite", path=path) as storage:
        storage.create_table("people", [Field("email")])
        storage.add_row("people", {"email": "bo@example.com"})
        schema.set_unique(storage, "people", "email", True)
    with open_database(backend="sqlite", path=path) as again, pytest.raises(JubakoError, match="cannot repeat"):
        again.add_row("people", {"email": "bo@example.com"})


def test_the_engine_refusing_a_repeat_comes_back_in_words(people):
    schema.set_unique(people, "people", "email", True)
    fields = people.describe_table("people").fields
    with pytest.raises(JubakoError, match="must not repeat"):
        people.add_rows("people", fields, [["Q", "ann@example.com", None]])


def _outside_table(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE birds (name VARCHAR(40), seen INTEGER, spotted DATE)")
    connection.executemany("INSERT INTO birds VALUES (?, ?, ?)",
                           [("Wren", 3, "2026-05-01"), ("Kite", None, None), ("Owl", 1, "2026-06-12")])
    connection.commit()
    connection.close()


def test_a_table_made_elsewhere_reads_but_does_not_edit_until_it_has_a_row_number(sandbox):
    from jubako.storage import create_database

    path = str(sandbox / "outside.jubadb")
    create_database(title="Outside", backend="sqlite", path=path).close()
    _outside_table(path)
    with open_database(backend="sqlite", path=path) as storage:
        info = storage.describe_table("birds")
        assert info.has_row_id is False
        page = storage.list_rows("birds", sort=[{"field": "name"}])
        assert page["editable"] is False
        assert [row[0] for row in page["rows"]] == [None, None, None]      # not the word "id"
        assert [row[1] for row in page["rows"]] == ["Kite", "Owl", "Wren"]
        with pytest.raises(JubakoError, match="no row number"):
            storage.update_row("birds", 1, {"seen": 4})
        with pytest.raises(JubakoError, match="no row number"):
            storage.delete_row("birds", 1)

        result = schema.add_row_number(storage, "birds")
        assert result["rows"] == 3
        page = storage.list_rows("birds")
        assert page["editable"] is True
        assert [row[:3] for row in page["rows"]] == [[1, "Wren", 3], [2, "Kite", None], [3, "Owl", 1]]
        assert storage.update_row("birds", 2, {"seen": 5}) is True
        assert storage.add_row("birds", {"name": "Tern"}) == 4
        with pytest.raises(JubakoError, match="already has a row number"):
            schema.add_row_number(storage, "birds")
