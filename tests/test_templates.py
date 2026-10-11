"""Templates: ready-made databases with tables, example rows, views, reports and forms."""

from __future__ import annotations

import pytest

from jubako import templates, views
from jubako.errors import JubakoError
from jubako.fields import Field
from jubako.reports import (
    fetch_lines,
    fetch_rows,
    form_for,
    list_reports,
    load_report,
    normalise_spec,
)


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
    database.create_table("contacts", [Field("name")])
    with pytest.raises(JubakoError, match="already has a table called 'contacts'"):
        templates.apply_template(database, "contacts")
    assert views.list_views(database) == []


def test_an_unknown_template_says_which_there_are():
    with pytest.raises(JubakoError, match="contacts, inventory"):
        templates.load_template("spaceships")


def test_a_template_replaces_views_left_over_from_a_table_long_gone(database):
    database.create_table("items", [Field("x")])
    views.save_view(database, "items", "Running low", {"field": "x", "op": "empty"})
    database.drop_table("items")              # the low-level drop leaves its views behind
    made = templates.apply_template(database, "inventory")
    assert "Running low" in made["views"]
    assert views.get_view(database, "items", "Running low")["filter"]["field"] == "quantity"


def test_the_projects_template_ties_each_task_to_its_project(database):
    templates.apply_template(database, "projects")
    project = next(f for f in database.describe_table("tasks").fields if f.name == "project")
    assert (project.type, project.target, project.show) == ("lookup", "projects", "project")
    page = database.list_rows("tasks", sort=[{"field": "project"}])
    at = page["columns"].index("project")
    assert [row[at] for row in page["rows"]][:2] == ["Move the stockroom", "New website"]
    # Renaming a project shows in its tasks; a project with tasks cannot be deleted.
    website = next(row for row in database.list_rows("projects")["rows"] if row[1] == "New website")
    database.update_row("projects", website[0], {"project": "Website"})
    words = [row[at] for row in database.list_rows("tasks")["rows"]]
    assert words.count("Website") == 3 and "New website" not in words
    with pytest.raises(JubakoError):
        database.delete_row("projects", website[0])
    report = normalise_spec(database, load_report(database, "Tasks by project"))
    headings = [line["text"] for line in fetch_lines(database, report) if line["kind"] == "group"]
    assert headings == ["Project: Spring catalogue", "Project: Website"]


def test_the_customer_service_template_ties_each_ticket_to_its_customer(database):
    templates.apply_template(database, "customer_service")
    customer = next(f for f in database.describe_table("tickets").fields if f.name == "customer")
    assert (customer.type, customer.target, customer.show) == ("lookup", "customers", "customer")
    assert database.count_rows("customers") == 5
    alvarez = next(row for row in database.list_rows("customers")["rows"] if row[1] == "M. Alvarez")
    database.update_row("customers", alvarez[0], {"customer": "Maria Alvarez"})
    at = database.list_rows("tickets")["columns"].index("customer")
    assert [row[at] for row in database.list_rows("tickets")["rows"]].count("Maria Alvarez") == 2
    with pytest.raises(JubakoError):
        database.delete_row("customers", alvarez[0])
    report = normalise_spec(database, load_report(database, "Tickets by customer"))
    lines = fetch_lines(database, report)
    headings = [line["text"] for line in lines if line["kind"] == "group"]
    assert headings[:2] == ["Customer: J. Mensah", "Customer: Maria Alvarez"] and len(headings) == 5


def test_the_inventory_template_ties_each_item_to_its_supplier(database):
    made = templates.apply_template(database, "inventory")
    assert made["tables"] == ["suppliers", "items"] and made["opens"] == "items"
    supplier = next(f for f in database.describe_table("items").fields if f.name == "supplier")
    assert (supplier.type, supplier.target, supplier.show) == ("lookup", "suppliers", "supplier")
    harbour = next(row for row in database.list_rows("suppliers")["rows"] if row[1] == "Harbour Trading")
    database.update_row("suppliers", harbour[0], {"supplier": "Harbour Trading Co"})
    at = database.list_rows("items")["columns"].index("supplier")
    assert [row[at] for row in database.list_rows("items")["rows"]].count("Harbour Trading Co") == 2
    with pytest.raises(JubakoError):
        database.delete_row("suppliers", harbour[0])
    # The shopping list still names each item's supplier.
    shopping = normalise_spec(database, load_report(database, "Shopping list"))
    assert [row[-1] for row in fetch_rows(database, shopping)] == ["Northwind Cycle Supply", "Harbour Trading Co"]
    report = normalise_spec(database, load_report(database, "Stock by supplier"))
    headings = [line["text"] for line in fetch_lines(database, report) if line["kind"] == "group"]
    assert headings == ["Supplier: Clearwater Oils", "Supplier: Harbour Trading Co", "Supplier: Northwind Cycle Supply"]


def test_a_template_opens_on_its_first_table_unless_it_says(database):
    made = templates.apply_template(database, "projects")
    assert made["tables"][0] == "projects" and made["opens"] == "projects"  # no "opens": the first table


def test_the_home_collection_template_ties_each_loan_to_a_person(database):
    made = templates.apply_template(database, "collection")
    assert made["tables"] == ["people", "collection"] and made["opens"] == "collection"
    lent_to = next(f for f in database.describe_table("collection").fields if f.name == "lent_to")
    assert (lent_to.type, lent_to.target, lent_to.show) == ("lookup", "people", "name")
    # Most things are not lent out: a blank lookup stays blank.
    lent = views.get_view(database, "collection", "Lent out")
    page = database.list_rows("collection", where=lent["filter"], sort=[{"field": "lent_to"}])
    at = page["columns"].index("lent_to")
    assert [(row[1], row[at]) for row in page["rows"]] == [("Starboard", "Chloe"), ("Night Trains", "Dev")]
    # Lending to Sam, who is in people, works by name; a stranger is refused.
    harbour = next(row for row in database.list_rows("collection")["rows"] if row[1] == "The Quiet Harbour")
    database.update_row("collection", harbour[0], {"lent_to": "sam"})
    with pytest.raises(JubakoError):
        database.update_row("collection", harbour[0], {"lent_to": "Someone new"})
    report = normalise_spec(database, load_report(database, "Who has what"))
    assert [row[-1] for row in fetch_rows(database, report)] == ["Chloe", "Dev", "Sam"]
    chloe = next(row for row in database.list_rows("people")["rows"] if row[1] == "Chloe")
    with pytest.raises(JubakoError):
        database.delete_row("people", chloe[0])


def test_the_contacts_template_puts_each_contact_in_a_group(database):
    made = templates.apply_template(database, "contacts")
    assert made["tables"] == ["contact_groups", "contacts"] and made["opens"] == "contacts"
    group = next(f for f in database.describe_table("contacts").fields if f.name == "contact_group")
    assert (group.type, group.target, group.show, group.title) == ("lookup", "contact_groups", "name", "Group")
    friends = database.list_rows("contacts", where={"field": "contact_group", "op": "is", "value": "friends"})
    assert sorted(row[1] for row in friends["rows"]) == ["Ada", "Dev"]
    work = next(row for row in database.list_rows("contact_groups")["rows"] if row[1] == "Work")
    with pytest.raises(JubakoError):
        database.delete_row("contact_groups", work[0])
    report = normalise_spec(database, load_report(database, "Contacts by group"))
    headings = [line["text"] for line in fetch_lines(database, report) if line["kind"] == "group"]
    assert headings == ["Group: Family", "Group: Friends", "Group: Neighbours", "Group: Services", "Group: Work"]
