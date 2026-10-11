"""Lookup fields: a row of one table pointing at a row of another."""

from __future__ import annotations

import pytest

from jubako import schema, views
from jubako.errors import JubakoError
from jubako.fields import LOOKUP, Field
from jubako.reports import fetch_rows, normalise_spec
from jubako.storage import create_database, open_database


@pytest.fixture
def shop(database):
    database.create_table("customers", [Field("name", label="Name"), Field("city", label="City")])
    for name, city in [("Ann Lee", "Bend"), ("Bo Diaz", "Salem"), ("Cy Park", "Bend")]:
        database.add_row("customers", {"name": name, "city": city})
    database.create_table("orders", [Field("item", label="Item"), Field("total", "real", label="Total")])
    schema.add_field(database, "orders", label="Customer", field_type=LOOKUP, target="customers", show="name")
    for item, total, customer in [("Bell", 4.5, "Ann Lee"), ("Bike", 300.0, "bo diaz"), ("Tube", 6.0, 3),
                                  ("Lock", 20.0, "#1"), ("Map", 2.0, None)]:
        database.add_row("orders", {"item": item, "total": total, "customer": customer})
    return database


def _column(page, name):
    position = page["columns"].index(name)
    return [row[position] for row in page["rows"]]


def test_a_lookup_keeps_the_row_number_and_shows_the_words(shop):
    page = shop.list_rows("orders")
    assert _column(page, "customer") == ["Ann Lee", "Bo Diaz", "Cy Park", "Ann Lee", None]
    assert page["ids"]["customer"] == [1, 2, 3, 1, None]
    field = next(f for f in page["fields"] if f["name"] == "customer")
    assert field == {"name": "customer", "type": "lookup", "label": "Customer", "target": "customers", "show": "name"}

    # Renaming the customer shows everywhere at once.
    shop.update_row("customers", 1, {"name": "Ann Lee-Park"})
    assert _column(shop.list_rows("orders"), "customer")[0] == "Ann Lee-Park"


def test_writes_name_the_row_and_are_checked_in_words(shop):
    with pytest.raises(JubakoError, match="No row of customers has Name “Dee”"):
        shop.add_row("orders", {"item": "Horn", "customer": "Dee"})
    with pytest.raises(JubakoError, match="customers has no row 99"):
        shop.add_row("orders", {"item": "Horn", "customer": 99})
    shop.add_row("customers", {"name": "Ann Lee", "city": "Eugene"})
    with pytest.raises(JubakoError, match="More than one row of customers has Name “ann lee”"):
        shop.add_row("orders", {"item": "Horn", "customer": "ann lee"})
    row_id = shop.add_row("orders", {"item": "Horn", "customer": "#4"})
    assert shop.list_rows("orders", where={"field": "item", "op": "is", "value": "Horn"})["ids"]["customer"] == [4]
    shop.update_row("orders", row_id, {"customer": "Cy Park"})
    assert shop.list_rows("orders", where={"field": "item", "op": "is", "value": "Horn"})["ids"]["customer"] == [3]


def test_a_lookup_must_point_at_a_words_field_of_a_real_table(shop):
    with pytest.raises(JubakoError, match="no table called 'nope'"):
        schema.add_field(shop, "orders", label="Shop", field_type=LOOKUP, target="nope", show="name")
    with pytest.raises(JubakoError, match="no field called 'phone'"):
        schema.add_field(shop, "orders", label="Shop", field_type=LOOKUP, target="customers", show="phone")
    with pytest.raises(JubakoError, match="only show a words field"):
        schema.add_field(shop, "customers", label="Big order", field_type=LOOKUP, target="orders", show="total")
    with pytest.raises(JubakoError, match="Say which table"):
        schema.add_field(shop, "orders", label="Shop", field_type=LOOKUP)


def test_filters_and_sorts_use_the_words(shop):
    def items(**kwargs):
        return _column(shop.list_rows("orders", **kwargs), "item")

    assert items(where={"field": "customer", "op": "is", "value": "ann lee"}) == ["Bell", "Lock"]
    assert items(where={"field": "customer", "op": "contains", "value": "PARK"}) == ["Tube"]
    assert items(where={"field": "customer", "op": "starts_with", "value": "b"}) == ["Bike"]
    assert items(where={"field": "customer", "op": "is_not", "value": "Ann Lee"}) == ["Bike", "Tube", "Map"]
    assert items(where={"field": "customer", "op": "empty"}) == ["Map"]
    assert items(where={"match": "all", "rules": [{"field": "customer", "op": "not_empty"},
                                                  {"field": "total", "op": "more_than", "value": 5}]}) == [
        "Bike", "Tube", "Lock"]
    assert items(sort=[{"field": "customer", "descending": False}]) == ["Bell", "Lock", "Bike", "Tube", "Map"]
    assert items(sort=[{"field": "customer", "descending": True}]) == ["Tube", "Bike", "Bell", "Lock", "Map"]
    with pytest.raises(JubakoError, match="only works on a number or a date"):
        shop.list_rows("orders", where={"field": "customer", "op": "more_than", "value": "A"})
    assert shop.count_rows("orders", where={"field": "customer", "op": "contains", "value": "lee"}) == 2


def test_a_saved_view_on_a_lookup_follows_a_renamed_customer(shop):
    views.save_view(shop, "orders", "Ann's", {"field": "customer", "op": "is", "value": "Ann Lee"},
                    sort=[{"field": "customer"}])
    view = views.get_view(shop, "orders", "Ann's")
    assert view["words"] == "Customer is Ann Lee · sorted by Customer, A to Z"
    assert _column(shop.list_rows("orders", where=view["filter"]), "item") == ["Bell", "Lock"]


def test_rows_others_point_at_cannot_be_deleted(shop):
    with pytest.raises(JubakoError, match="2 rows of orders still point at this row through Customer"):
        shop.delete_row("customers", 1)
    with pytest.raises(JubakoError, match="1 row of orders still points|1 row of orders still point"):
        shop.delete_matching("customers", {"field": "city", "op": "is", "value": "Salem"})
    shop.update_row("orders", 2, {"customer": None})
    assert shop.delete_matching("customers", {"field": "city", "op": "is", "value": "Salem"}) == 1
    # Once nothing points at it, a row goes.
    shop.add_row("customers", {"name": "Dee"})
    assert shop.delete_row("customers", 4) is True


def test_the_table_and_the_field_a_lookup_shows_are_protected_and_renames_follow(shop):
    with pytest.raises(JubakoError, match="Customer in orders points at rows of customers"):
        schema.drop_table(shop, "customers")
    with pytest.raises(JubakoError, match="Customer in orders shows this field"):
        schema.drop_field(shop, "customers", "name")
    schema.rename_field(shop, "customers", "name", "full_name")
    field = next(f for f in shop.describe_table("orders").fields if f.name == "customer")
    assert field.show == "full_name"
    assert _column(shop.list_rows("orders"), "customer")[0] == "Ann Lee"
    # Renaming the lookup itself keeps what it points at.
    schema.rename_field(shop, "orders", "customer", "buyer")
    field = next(f for f in shop.describe_table("orders").fields if f.name == "buyer")
    assert (field.type, field.target, field.show) == (LOOKUP, "customers", "full_name")
    # Deleting the lookup frees the table.
    schema.drop_field(shop, "orders", "buyer")
    assert schema.drop_table(shop, "customers")["rows_deleted"] == 3


def test_a_lookup_survives_closing_the_database(sandbox):
    path = str(sandbox / "kept.jubadb")
    with create_database(title="Kept", backend="sqlite", path=path) as storage:
        storage.create_table("people", [Field("name")])
        storage.add_row("people", {"name": "Ann"})
        storage.create_table("pets", [Field("pet"), Field("owner", LOOKUP, target="people", show="name")])
        storage.add_row("pets", {"pet": "Rex", "owner": "Ann"})
    with open_database(backend="sqlite", path=path) as storage:
        page = storage.list_rows("pets")
        assert page["rows"][0][1:] == ["Rex", "Ann"] and page["ids"]["owner"] == [1]


def test_a_table_can_look_into_itself(database):
    database.create_table("staff", [Field("name"), Field("boss", LOOKUP, target="staff", show="name")])
    database.add_row("staff", {"name": "Ann"})
    database.add_row("staff", {"name": "Bo", "boss": "Ann"})
    assert _column(database.list_rows("staff"), "boss") == [None, "Ann"]
    with pytest.raises(JubakoError, match="still point at this row"):
        database.delete_row("staff", 1)


def test_a_words_field_becomes_a_lookup(database):
    database.create_table("customers", [Field("name", label="Name")])
    for name in ("Ann Lee", "Bo Diaz"):
        database.add_row("customers", {"name": name})
    database.create_table("orders", [Field("item"), Field("customer", label="Customer")])
    for item, customer in [("Bell", "Ann Lee"), ("Bike", " ann lee "), ("Tube", "Cy Park"), ("Lock", "Dee"),
                           ("Map", None)]:
        database.add_row("orders", {"item": item, "customer": customer})
    views.save_view(database, "orders", "Ann's", {"field": "customer", "op": "is", "value": "Ann Lee"})

    with pytest.raises(JubakoError, match="2 values of Customer match no row of customers by Name: “Cy Park”, “Dee”"):
        schema.make_lookup(database, "orders", "customer", "customers", "name")
    assert database.describe_table("orders").fields[1].type == "text"  # nothing changed

    result = schema.make_lookup(database, "orders", "customer", "customers", "name", add_missing=True)
    assert result["added"] == ["Cy Park", "Dee"]
    page = database.list_rows("orders")
    assert _column(page, "customer") == ["Ann Lee", "Ann Lee", "Cy Park", "Dee", None]
    assert page["ids"]["customer"] == [1, 1, 3, 4, None]
    assert [f["name"] for f in page["fields"]] == ["item", "customer"]  # still in its place
    # The view saved on the words still finds the same rows.
    view = views.get_view(database, "orders", "Ann's")
    assert _column(database.list_rows("orders", where=view["filter"]), "item") == ["Bell", "Bike"]

    with pytest.raises(JubakoError, match="already points at rows of customers"):
        schema.make_lookup(database, "orders", "customer", "customers", "name")


def test_making_a_lookup_refuses_words_that_two_rows_have(database):
    database.create_table("customers", [Field("name")])
    for name in ("Ann", "ann", "Bo"):
        database.add_row("customers", {"name": name})
    database.create_table("orders", [Field("customer")])
    database.add_row("orders", {"customer": "Ann"})
    with pytest.raises(JubakoError, match="More than one row of customers has Name “Ann”"):
        schema.make_lookup(database, "orders", "customer", "customers", "name")


def test_reports_exports_and_summaries_show_the_words(shop, sandbox):
    from jubako.exporter import export_table

    spec = normalise_spec(shop, {"table": "orders", "columns": ["item", "customer"], "group_by": "customer",
                                 "sort": [{"field": "item"}]})
    assert fetch_rows(shop, spec)[:2] == [["Bell", "Ann Lee"], ["Lock", "Ann Lee"]]
    target = sandbox / "orders.csv"
    export_table(shop, "orders", str(target))
    lines = target.read_text("utf-8").splitlines()
    assert lines[1].endswith(",Ann Lee") and lines[5].endswith(",")
    summary = shop.summarize("orders", {"field": "customer", "op": "contains", "value": "lee"})
    assert summary["rows"] == 2
    assert next(f for f in summary["fields"] if f["name"] == "customer")["filled"] == 2
    changed = shop.update_matching("orders", {"field": "customer", "op": "empty"}, {"customer": "Cy Park"})
    assert changed == 1 and shop.list_rows("orders")["ids"]["customer"][-1] == 3


def test_lookups_through_the_tools_and_the_command_line(sandbox, capsys):
    from jubako.cli import main as cli
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "tools.jubadb")
    HANDLERS["create_database"]({"title": "Tools", "path": db})
    with open_database(backend="sqlite", path=db) as storage:
        storage.create_table("customers", [Field("name")])
        storage.add_row("customers", {"name": "Ann"})
        storage.create_table("orders", [Field("item"), Field("customer")])
        storage.add_row("orders", {"item": "Bell", "customer": "Ann"})
        storage.add_row("orders", {"item": "Bike", "customer": "Bo"})

    with pytest.raises(JubakoError, match="match no row of customers"):
        HANDLERS["make_lookup"]({"path": db, "table": "orders", "field": "customer", "target": "customers", "show": "name"})
    made = HANDLERS["make_lookup"]({"path": db, "table": "orders", "field": "customer", "target": "customers",
                                    "show": "name", "add_missing": True})
    assert made["added"] == ["Bo"] and made["fields"][1]["target"] == "customers"
    rows = HANDLERS["list_rows"]({"path": db, "table": "orders"})
    assert [row[2] for row in rows["rows"]] == ["Ann", "Bo"] and rows["ids"]["customer"] == [1, 2]
    HANDLERS["add_row"]({"path": db, "table": "orders", "values": {"item": "Tube", "customer": "ann"}})
    assert HANDLERS["list_rows"]({"path": db, "table": "orders"})["ids"]["customer"][-1] == 1
    described = HANDLERS["describe_table"]({"path": db, "table": "orders"})
    assert "lookup" in described["field_types"]

    added = HANDLERS["add_field"]({"path": db, "table": "customers", "label": "Referred by", "type": "lookup",
                                   "target": "customers", "show": "name"})
    assert added["fields"][-1] == {"name": "referred_by", "type": "lookup", "label": "Referred by",
                                   "target": "customers", "show": "name"}

    assert cli(["lookup", db, "orders", "helper", "--to", "customers", "--show", "name", "--label", "Helper"]) == 0
    assert "Added helper to orders" in capsys.readouterr().out
    with open_database(backend="sqlite", path=db) as storage:
        storage.create_table("notes", [Field("text"), Field("who")])
        storage.add_row("notes", {"text": "hi", "who": "Cy"})
    assert cli(["lookup", db, "notes", "who", "--to", "customers", "--show", "name", "--add-missing"]) == 0
    assert "who now points at rows of customers, showing name. Added 1 to customers: Cy." in capsys.readouterr().out
