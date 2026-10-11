"""Templates: ready-made databases with tables, example rows, views, reports and forms."""

from __future__ import annotations

import pytest

from jubako import templates, views
from jubako.errors import JubakoError
from jubako.reports import fetch_rows, form_for, list_reports, load_report, normalise_spec


def test_every_template_is_listed_in_order():
    listed = templates.list_templates()
    assert [t["key"] for t in listed] == ["contacts", "inventory", "projects", "customer_service", "collection"]
    for item in listed:
        assert item["title"] and item["blurb"] and item["tables"]


@pytest.mark.parametrize("key", [t["key"] for t in templates.list_templates()])
def test_each_template_applies_and_everything_in_it_works(database, key):
    made = templates.apply_template(database, key)
    template = templates.load_template(key)
    assert made["tables"] == [t["name"] for t in template["tables"]]
    assert sorted(made["tables"]) == database.list_tables()
    assert made["rows_added"] == sum(len(t.get("rows", [])) for t in template["tables"])
    for table in template["tables"]:
        assert database.count_rows(table["name"]) == len(table.get("rows", []))
        # Every example row fits its fields (coerce would have refused it otherwise) and lines up.
        assert all(len(row) == len(table["fields"]) for row in table.get("rows", []))
    # Views apply, reports lay out, forms load.
    for view in views.list_views(database):
        database.list_rows(view["table"], where=view.get("filter"), sort=view.get("sort"))
    assert sorted(r["name"] for r in list_reports(database)) == sorted(made["reports"])
    for name in made["reports"]:
        spec = normalise_spec(database, load_report(database, name))
        assert fetch_rows(database, spec)
    for form in template.get("forms", []):
        assert form_for(database, form["table"])["saved"] is True
    # One default view at most per table.
    for table in database.list_tables():
        assert sum(1 for v in views.list_views(database, table) if v.get("default")) <= 1


def test_a_template_without_example_rows(database):
    made = templates.apply_template(database, "inventory", sample_rows=False)
    assert made["rows_added"] == 0
    assert database.count_rows("items") == 0
    assert [v["name"] for v in views.list_views(database, "items")] == ["By category", "Out of stock", "Running low"]


def test_template_views_and_reports_do_what_they_say(database):
    templates.apply_template(database, "inventory")
    low = views.get_view(database, "items", "Running low")
    page = database.list_rows("items", where=low["filter"], sort=low["sort"])
    assert [row[1] for row in page["rows"]] == ["Mini pump", "Bell, brass"]
    shopping = normalise_spec(database, load_report(database, "Shopping list"))
    assert shopping["view"] == "Running low" and len(fetch_rows(database, shopping)) == 2


def test_a_template_refuses_a_database_that_has_its_tables(database):
    database.create_table("contacts", [templates.Field("name")])
    with pytest.raises(JubakoError, match="already has a table called 'contacts'"):
        templates.apply_template(database, "contacts")
    assert views.list_views(database) == []


def test_an_unknown_template_says_which_there_are():
    with pytest.raises(JubakoError, match="contacts, inventory"):
        templates.load_template("spaceships")


def test_a_template_replaces_views_left_over_from_a_table_long_gone(database):
    database.create_table("items", [templates.Field("x")])
    views.save_view(database, "items", "Running low", {"field": "x", "op": "empty"})
    database.drop_table("items")              # the low-level drop leaves its views behind
    made = templates.apply_template(database, "inventory")
    assert "Running low" in made["views"]
    assert views.get_view(database, "items", "Running low")["filter"]["field"] == "quantity"
