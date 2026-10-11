"""Show rows where ... : the one filter behind the grid, the form, reports and MCP."""

from __future__ import annotations

import pytest

from jubako import schema
from jubako.errors import BadName, JubakoError
from jubako.fields import Field
from jubako.filters import filter_words, normalise_filter
from jubako.importer import import_spreadsheet
from jubako.reports import export_report, fetch_rows, normalise_spec


@pytest.fixture
def pets(database, pets_csv):
    import_spreadsheet(database, str(pets_csv))
    schema.add_field(database, "pets", label="Moved", field_type="boolean")
    ids = [row[0] for row in database.list_rows("pets")["rows"]]
    database.update_row("pets", ids[0], {"moved": "yes"})
    database.update_row("pets", ids[2], {"moved": True})
    return database


def names(page):
    return [row[1] for row in page["rows"]]


def test_add_field_appends_a_blank_column(database, pets_csv):
    import_spreadsheet(database, str(pets_csv))
    result = schema.add_field(database, "pets", label="Moved", field_type="boolean")
    assert result["fields"][-1] == {"name": "moved", "type": "boolean", "label": "Moved"}
    page = database.list_rows("pets")
    assert page["columns"][-1] == "moved"
    assert [row[-1] for row in page["rows"]] == [None, None, None, None]
    assert schema.add_field(database, "pets", label="Vet's phone")["fields"][-1]["name"] == "vet_s_phone"
    assert schema.add_field(database, "pets", label="Fee", name="fee_usd", field_type="real")["fields"][-1]["name"] == "fee_usd"
    with pytest.raises(BadName):
        schema.add_field(database, "pets", label="Moved")
    with pytest.raises(BadName):
        schema.add_field(database, "pets", label="Row", name="id")
    with pytest.raises(JubakoError, match="Unknown field type"):
        schema.add_field(database, "pets", label="X", field_type="blob")
    with pytest.raises(JubakoError, match="label"):
        schema.add_field(database, "pets", label="   ")


def test_is_and_is_not_on_a_yes_no_field(pets):
    hide_moved = {"field": "moved", "op": "is_not", "value": "yes"}
    page = pets.list_rows("pets", where=hide_moved)
    assert names(page) == ["Milo", "Pip"]        # blanks count as "not yes"
    assert page["total"] == 2
    assert page["total_all"] == 4
    assert page["filter"] == {"field": "moved", "op": "is_not", "value": True}
    for word in ("yes", "true", "1", "Y", True):
        assert names(pets.list_rows("pets", where={"field": "moved", "op": "is", "value": word})) == ["Rex", "Shadow"]
    assert pets.count_rows("pets", where=hide_moved) == 2
    assert pets.count_rows("pets") == 4


def test_empty_not_empty_and_contains(pets):
    assert names(pets.list_rows("pets", where={"field": "moved", "op": "empty"})) == ["Milo", "Pip"]
    assert names(pets.list_rows("pets", where={"field": "moved", "op": "not_empty"})) == ["Rex", "Shadow"]
    assert names(pets.list_rows("pets", where={"field": "name", "op": "contains", "value": "i"})) == ["Milo", "Pip"]
    assert names(pets.list_rows("pets", where={"field": "name", "op": "contains", "value": "%"})) == []
    assert names(pets.list_rows("pets", where={"field": "age", "op": "is", "value": "4"})) == ["Rex"]
    assert names(pets.list_rows("pets", where={"field": "adopted_on", "op": "is", "value": "2024-01-05"})) == ["Pip"]
    assert names(pets.list_rows("pets", where={"field": "age", "op": "is empty"})) == ["Pip"]


def test_filters_are_checked_in_words(pets):
    fields = pets.describe_table("pets").fields
    with pytest.raises(BadName):
        normalise_filter(fields, {"field": "colour", "op": "is", "value": "red"})
    with pytest.raises(JubakoError, match="Unknown match"):
        normalise_filter(fields, {"field": "name", "op": "like", "value": "x"})
    with pytest.raises(JubakoError, match="Say what"):
        normalise_filter(fields, {"field": "name", "op": "is", "value": ""})
    with pytest.raises(JubakoError, match="not a whole number"):
        normalise_filter(fields, {"field": "age", "op": "is", "value": "old"})
    with pytest.raises(JubakoError, match="only works on a words field"):
        normalise_filter(fields, {"field": "age", "op": "contains", "value": "4"})
    assert normalise_filter(fields, None) is None
    assert normalise_filter(fields, {}) is None
    # No SQL sneaks in: the field must be a real one, the value is bound.
    with pytest.raises(BadName):
        normalise_filter(fields, {"field": "name; DROP TABLE pets", "op": "is", "value": "x"})
    assert names(pets.list_rows("pets", where={"field": "name", "op": "is", "value": "Rex' OR 1=1 --"})) == []


def test_filter_words(pets):
    fields = pets.describe_table("pets").fields
    assert filter_words(fields, normalise_filter(fields, {"field": "moved", "op": "is_not", "value": "yes"})) == "Moved is not Yes"
    assert filter_words(fields, normalise_filter(fields, {"field": "name", "op": "empty"})) == "name is empty"
    assert filter_words(fields, normalise_filter(fields, {"field": "name", "op": "contains", "value": "Re"})) == "name contains Re"
    assert filter_words(fields, None) == ""


def test_reports_honour_the_filter(pets, sandbox):
    pytest.importorskip("PySide6")
    spec = normalise_spec(pets, {"table": "pets", "columns": ["name", "moved"],
                                 "filter": {"field": "moved", "op": "is_not", "value": "yes"}})
    assert spec["filter_words"] == "Moved is not Yes"
    assert fetch_rows(pets, spec) == [["Milo", ""], ["Pip", ""]]
    result = export_report(pets, spec, str(sandbox / "not-moved.pdf"))
    assert result["rows_written"] == 2
    plain = normalise_spec(pets, {"table": "pets"})
    assert plain["filter"] is None and plain["filter_words"] == ""
    with pytest.raises(BadName):
        normalise_spec(pets, {"table": "pets", "filter": {"field": "nope", "op": "is", "value": 1}})


# -- comparisons, several rules, sorting --------------------------------------

def test_comparisons_on_numbers_and_dates(pets):
    assert names(pets.list_rows("pets", where={"field": "age", "op": "more_than", "value": "3"})) == ["Rex", "Shadow"]
    assert names(pets.list_rows("pets", where={"field": "age", "op": "at_least", "value": 4})) == ["Rex", "Shadow"]
    assert names(pets.list_rows("pets", where={"field": "age", "op": "less_than", "value": "4"})) == ["Milo"]
    assert names(pets.list_rows("pets", where={"field": "age", "op": "at_most", "value": "4"})) == ["Rex", "Milo"]
    assert names(pets.list_rows("pets", where={"field": "weight_kg", "op": ">", "value": "5"})) == ["Rex", "Shadow"]
    assert names(pets.list_rows("pets", where={"field": "adopted_on", "op": "after", "value": "2023-06-01"})) == ["Milo", "Pip"]
    assert names(pets.list_rows("pets", where={"field": "adopted_on", "op": "before", "value": "2021-03-14"})) == ["Shadow"]
    assert names(pets.list_rows("pets", where={"field": "adopted_on", "op": "on_or_before", "value": "2021-03-14"})) == ["Rex", "Shadow"]
    assert names(pets.list_rows("pets", where={"field": "name", "op": "starts_with", "value": "sH"})) == ["Shadow"]
    assert names(pets.list_rows("pets", where={"field": "name", "op": "starts_with", "value": "_"})) == []


def test_comparisons_are_checked_in_words(pets):
    fields = pets.describe_table("pets").fields
    with pytest.raises(JubakoError, match="only works on a number or a date"):
        normalise_filter(fields, {"field": "name", "op": "more_than", "value": "b"})
    with pytest.raises(JubakoError, match="only works on a number or a date"):
        normalise_filter(fields, {"field": "moved", "op": "less_than", "value": "yes"})
    with pytest.raises(JubakoError, match="not a date"):
        normalise_filter(fields, {"field": "adopted_on", "op": "after", "value": "soon"})
    with pytest.raises(JubakoError, match="only works on a words field"):
        normalise_filter(fields, {"field": "age", "op": "starts_with", "value": "1"})
    with pytest.raises(JubakoError, match="Say what adopted_on is after"):
        normalise_filter(fields, {"field": "adopted_on", "op": "after", "value": ""})


def test_several_rules_all_or_any(pets):
    both = {"match": "all", "rules": [
        {"field": "age", "op": "more_than", "value": "3"},
        {"field": "moved", "op": "is", "value": "yes"},
    ]}
    page = pets.list_rows("pets", where=both)
    assert names(page) == ["Rex", "Shadow"]
    either = {"match": "any", "rules": [
        {"field": "age", "op": "empty"},
        {"field": "name", "op": "is", "value": "Milo"},
    ]}
    assert names(pets.list_rows("pets", where=either)) == ["Milo", "Pip"]
    assert pets.count_rows("pets", where=either) == 2
    narrower = {"match": "all", "rules": [
        {"field": "age", "op": "more_than", "value": "3"},
        {"field": "name", "op": "contains", "value": "sha"},
    ]}
    assert names(pets.list_rows("pets", where=narrower)) == ["Shadow"]
    # One rule in a list reads the same as the plain rule; an empty list is no filter.
    fields = pets.describe_table("pets").fields
    assert normalise_filter(fields, {"match": "any", "rules": [{"field": "age", "op": "empty"}]}) == {
        "field": "age", "op": "empty", "value": None}
    assert normalise_filter(fields, {"match": "all", "rules": []}) is None
    with pytest.raises(JubakoError, match="all or any"):
        normalise_filter(fields, {"match": "most", "rules": [{"field": "age", "op": "empty"}] * 2})
    with pytest.raises(JubakoError, match="at most 10"):
        normalise_filter(fields, {"match": "all", "rules": [{"field": "age", "op": "empty"}] * 11})


def test_several_rules_in_words(pets):
    fields = pets.describe_table("pets").fields
    spec = normalise_filter(fields, {"match": "any", "rules": [
        {"field": "adopted_on", "op": "after", "value": "2023-01-01"},
        {"field": "moved", "op": "is", "value": "no"},
    ]})
    assert filter_words(fields, spec) == "adopted_on is after 2023-01-01 or Moved is No"


def test_sort_puts_blanks_last_and_breaks_ties_by_row(pets):
    assert names(pets.list_rows("pets", sort=[{"field": "age"}])) == ["Milo", "Rex", "Shadow", "Pip"]
    assert names(pets.list_rows("pets", sort=[{"field": "age", "descending": True}])) == ["Shadow", "Rex", "Milo", "Pip"]
    # Moved is Yes for Rex and Shadow; ties fall back to the order rows were added.
    assert names(pets.list_rows("pets", sort=[{"field": "moved", "descending": True}, "name"])) == [
        "Rex", "Shadow", "Milo", "Pip"]
    page = pets.list_rows("pets", sort={"field": "name"}, where={"field": "age", "op": "not_empty"})
    assert names(page) == ["Milo", "Rex", "Shadow"]
    assert page["sort"] == [{"field": "name", "descending": False}]
    # The older one-field way still works.
    assert names(pets.list_rows("pets", order_by="name", descending=True)) == ["Shadow", "Rex", "Pip", "Milo"]
    assert names(pets.list_rows("pets", descending=True)) == ["Pip", "Shadow", "Milo", "Rex"]
    with pytest.raises(BadName):
        pets.list_rows("pets", sort=[{"field": "colour"}])
    with pytest.raises(JubakoError, match="at most 3"):
        pets.list_rows("pets", sort=["name", "age", "moved", "weight_kg"])


def test_sort_words():
    from jubako.filters import sort_words

    fields = [Field("name"), Field("age", "integer"), Field("born", "date", "Born")]
    assert sort_words(fields, [{"field": "age", "descending": True}, {"field": "name", "descending": False}]) == (
        "Age, highest first, then Name, A to Z")
    assert sort_words(fields, [{"field": "born", "descending": True}]) == "Born, newest first"
    assert sort_words(fields, []) == ""


# -- doing things with the rows a filter finds --------------------------------------

def test_change_every_matching_row(pets):
    changed = pets.update_matching("pets", {"field": "age", "op": "more_than", "value": 3}, {"moved": "no"})
    assert changed == 2
    assert names(pets.list_rows("pets", where={"field": "moved", "op": "is", "value": "no"})) == ["Rex", "Shadow"]
    assert pets.update_matching("pets", {"field": "name", "op": "is", "value": "Pip"}, {"age": None}) == 1
    with pytest.raises(JubakoError, match="every row"):
        pets.update_matching("pets", None, {"moved": "yes"})
    assert pets.update_matching("pets", None, {"moved": "yes"}, every_row=True) == 4
    with pytest.raises(JubakoError, match="age needs a whole number. “old” does not fit"):
        pets.update_matching("pets", None, {"age": "old"}, every_row=True)


def test_change_matching_rows_respects_no_repeats(pets):
    schema.set_unique(pets, "pets", "name", True)
    with pytest.raises(JubakoError, match="cannot be set to one value in 2 rows"):
        pets.update_matching("pets", {"field": "moved", "op": "is", "value": "yes"}, {"name": "Twin"})
    with pytest.raises(JubakoError, match="“Rex” is already in another row"):
        pets.update_matching("pets", {"field": "name", "op": "is", "value": "Pip"}, {"name": "Rex"})
    assert pets.update_matching("pets", {"field": "name", "op": "is", "value": "Pip"}, {"name": "Pippa"}) == 1


def test_delete_every_matching_row(pets):
    with pytest.raises(JubakoError, match="every row"):
        pets.delete_matching("pets", None)
    assert pets.delete_matching("pets", {"match": "any", "rules": [
        {"field": "age", "op": "empty"}, {"field": "name", "op": "is", "value": "Milo"}]}) == 2
    assert names(pets.list_rows("pets")) == ["Rex", "Shadow"]
    assert pets.delete_matching("pets", {"field": "name", "op": "is", "value": "Nobody"}) == 0
    assert pets.delete_matching("pets", None, every_row=True) == 2


def test_summarize_the_matching_rows(pets):
    summary = pets.summarize("pets")
    assert summary["rows"] == 4
    by_name = {item["name"]: item for item in summary["fields"]}
    assert by_name["age"] == {"name": "age", "label": "age", "type": "integer", "filled": 3,
                              "total": 17, "average": 5.67, "lowest": 2, "highest": 11}
    assert by_name["adopted_on"]["earliest"] == "2014-11-30" and by_name["adopted_on"]["latest"] == "2024-01-05"
    assert by_name["moved"]["yes"] == 2
    assert by_name["weight_kg"]["total"] == 23.85
    found = pets.summarize("pets", {"field": "moved", "op": "is", "value": "yes"})
    assert found["rows"] == 2 and {i["name"]: i for i in found["fields"]}["age"]["total"] == 15
    empty = pets.summarize("pets", {"field": "name", "op": "is", "value": "Nobody"})
    assert empty["rows"] == 0 and {i["name"]: i for i in empty["fields"]}["age"]["total"] is None


def test_a_whole_number_on_a_decimal_field_reads_without_point_zero(pets):
    fields = pets.describe_table("pets").fields
    spec = normalise_filter(fields, {"field": "weight_kg", "op": "more_than", "value": "3000"})
    assert spec["value"] == 3000.0
    assert filter_words(fields, spec) == "weight_kg is more than 3000"
    halves = normalise_filter(fields, {"field": "weight_kg", "op": "at_least", "value": "4.5"})
    assert filter_words(fields, halves) == "weight_kg is at least 4.5"
