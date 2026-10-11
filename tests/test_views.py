"""Saved views: named filters that live in the .jubadb."""

from __future__ import annotations

import pytest

from jubako import schema, views
from jubako.errors import JubakoError
from jubako.importer import import_spreadsheet
from jubako.storage import open_database

STILL_HERE = {"field": "moved", "op": "is_not", "value": "yes"}


@pytest.fixture
def pets(database, pets_csv):
    import_spreadsheet(database, str(pets_csv))
    schema.add_field(database, "pets", label="Moved", field_type="boolean")
    ids = [row[0] for row in database.list_rows("pets")["rows"]]
    database.update_row("pets", ids[0], {"moved": "yes"})
    return database


def test_save_list_apply_delete(pets):
    assert views.list_views(pets) == []
    view = views.save_view(pets, "pets", "Still here", STILL_HERE)
    assert view["name"] == "Still here"
    assert view["filter"] == {"field": "moved", "op": "is_not", "value": True}
    assert view["words"] == "Moved is not Yes"
    assert view["default"] is False and view["replaced"] is False
    assert [v["name"] for v in views.list_views(pets, "pets")] == ["Still here"]
    got = views.get_view(pets, "pets", "Still here")
    page = pets.list_rows("pets", where=got["filter"])
    assert [row[1] for row in page["rows"]] == ["Milo", "Shadow", "Pip"]
    assert views.delete_view(pets, "pets", "Still here") is True
    assert views.delete_view(pets, "pets", "Still here") is False
    assert pets.count_rows("pets") == 4  # the rows stay


def test_views_survive_close_and_reopen(sandbox, pets_csv):
    from jubako.storage import create_database

    path = str(sandbox / "kept.jubadb")
    first = create_database(title="Kept", path=path)
    import_spreadsheet(first, str(pets_csv))
    schema.add_field(first, "pets", label="Moved", field_type="boolean")
    first.update_row("pets", first.list_rows("pets")["rows"][0][0], {"moved": "yes"})
    views.save_view(first, "pets", "Still here", STILL_HERE, default=True)
    first.close()
    with open_database(path=path) as again:
        found = views.list_views(again, "pets")
        assert [v["name"] for v in found] == ["Still here"]
        assert views.default_view(again, "pets")["name"] == "Still here"
        page = again.list_rows("pets", where=found[0]["filter"])
        assert page["total"] == 3


def test_names_are_checked(pets):
    with pytest.raises(JubakoError, match="name"):
        views.save_view(pets, "pets", "  ", STILL_HERE)
    with pytest.raises(JubakoError, match="colon"):
        views.save_view(pets, "pets", "a:b", STILL_HERE)
    with pytest.raises(JubakoError, match="Apply a filter or a sort first"):
        views.save_view(pets, "pets", "Nothing", None)
    views.save_view(pets, "pets", "Still here", STILL_HERE)
    with pytest.raises(JubakoError, match="already a view"):
        views.save_view(pets, "pets", "Still here", {"field": "moved", "op": "empty"})
    replaced = views.save_view(pets, "pets", "Still here", {"field": "moved", "op": "empty"}, replace=True)
    assert replaced["replaced"] is True and replaced["words"] == "Moved is empty"
    with pytest.raises(JubakoError):
        views.save_view(pets, "pets", "Broken", {"field": "colour", "op": "is", "value": "red"})


def test_one_default_per_table(pets):
    views.save_view(pets, "pets", "A", STILL_HERE, default=True)
    views.save_view(pets, "pets", "B", {"field": "moved", "op": "empty"}, default=True)
    assert views.default_view(pets, "pets")["name"] == "B"
    assert views.get_view(pets, "pets", "A")["default"] is False
    # Replacing a view keeps its default flag unless told otherwise.
    views.save_view(pets, "pets", "B", {"field": "moved", "op": "not_empty"}, replace=True)
    assert views.get_view(pets, "pets", "B")["default"] is True


def test_rename_view(pets):
    views.save_view(pets, "pets", "Still here", STILL_HERE)
    renamed = views.rename_view(pets, "pets", "Still here", "Not moved")
    assert renamed["name"] == "Not moved"
    assert [v["name"] for v in views.list_views(pets, "pets")] == ["Not moved"]
    with pytest.raises(JubakoError, match="no view"):
        views.rename_view(pets, "pets", "Still here", "X")


def test_views_follow_a_field_rename_and_go_with_a_drop(pets):
    views.save_view(pets, "pets", "Still here", STILL_HERE)
    views.save_view(pets, "pets", "Young", {"field": "age", "op": "is", "value": "2"})
    schema.rename_field(pets, "pets", "moved", "gone", label="Gone away")
    view = views.get_view(pets, "pets", "Still here")
    assert view["filter"]["field"] == "gone"
    assert view["words"] == "Gone away is not Yes"
    schema.drop_field(pets, "pets", "gone")
    assert [v["name"] for v in views.list_views(pets, "pets")] == ["Young"]
    result = schema.drop_table(pets, "pets")
    assert result["views_forgotten"] == ["Young"]
    assert views.list_views(pets) == []


def test_views_keep_a_sort_and_several_rules(database, pets_csv):
    from jubako import schema
    from jubako.importer import import_spreadsheet

    import_spreadsheet(database, str(pets_csv))
    rules = {"match": "any", "rules": [
        {"field": "age", "op": "more_than", "value": "5"},
        {"field": "age", "op": "empty"},
    ]}
    view = views.save_view(database, "pets", "Old or unknown", rules, sort=[{"field": "name", "descending": True}])
    assert view["words"] == "age is more than 5 or age is empty · sorted by name, Z to A"
    kept = views.get_view(database, "pets", "Old or unknown")
    page = database.list_rows("pets", where=kept["filter"], sort=kept["sort"])
    assert [row[1] for row in page["rows"]] == ["Shadow", "Pip"]

    sorted_only = views.save_view(database, "pets", "Heaviest", None, sort=[{"field": "weight_kg", "descending": True}])
    assert sorted_only["filter"] is None

    # Renaming a field follows into the rules and the sort.
    schema.rename_field(database, "pets", "age", "years")
    kept = views.get_view(database, "pets", "Old or unknown")
    assert [rule["field"] for rule in kept["filter"]["rules"]] == ["years", "years"]
    # Dropping a field a view only sorts by keeps the view, without that sort ...
    schema.rename_field(database, "pets", "name", "pet_name")
    schema.drop_field(database, "pets", "pet_name")
    kept = views.get_view(database, "pets", "Old or unknown")
    assert kept["sort"] == [] and kept["words"] == "age is more than 5 or age is empty"  # the label stays
    # ... and a view left with nothing to do goes; one whose rules used the field goes too.
    schema.drop_field(database, "pets", "weight_kg")
    assert views.get_view(database, "pets", "Heaviest") is None
    schema.drop_field(database, "pets", "years")
    assert views.get_view(database, "pets", "Old or unknown") is None
