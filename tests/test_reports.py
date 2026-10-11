"""Reports: fitting columns, laying out pages, writing PDF; and remembered forms."""

from __future__ import annotations

from pathlib import Path

import pytest

from jubako.errors import BadName, JubakoError
from jubako.fields import Field
from jubako.importer import import_spreadsheet
from jubako.reports import (
    delete_report,
    export_report,
    fetch_rows,
    fit_columns,
    form_for,
    list_reports,
    load_report,
    normalise_spec,
    save_form,
    save_report,
)


def test_fit_columns_keeps_what_fits_and_shares_the_rest():
    assert fit_columns([100, 100], [20, 20], 400) == [100, 100]
    widths = fit_columns([100, 300, 50], [30, 60, 30], 300)
    assert widths == [100, 150.0, 50]
    assert sum(widths) <= 300


def test_fit_columns_scales_everything_when_even_minimums_do_not_fit():
    widths = fit_columns([200, 200], [150, 150], 200)
    assert sum(widths) == pytest.approx(200)
    assert widths[0] == pytest.approx(widths[1])


def test_fit_columns_can_be_turned_off():
    assert fit_columns([300, 300], [10, 10], 100, fit=False) == [300, 300]
    assert fit_columns([], [], 100) == []


def test_normalise_spec_fills_defaults_and_checks_columns(database, pets_csv: Path):
    import_spreadsheet(database, str(pets_csv))
    spec = normalise_spec(database, {"table": "pets"})
    assert spec["title"] == "Pets"
    assert spec["columns"] == ["name", "age", "adopted_on", "is_good", "weight_kg"]
    assert spec["page_size"] == "letter"
    assert spec["orientation"] == "portrait"
    assert spec["fit_to_width"] is True
    with pytest.raises(BadName):
        normalise_spec(database, {"table": "pets", "columns": ["name", "colour"]})
    with pytest.raises(JubakoError, match="page size"):
        normalise_spec(database, {"table": "pets", "page_size": "tabloid"})


def test_fetch_rows_gives_display_text_in_column_order(database, pets_csv: Path):
    import_spreadsheet(database, str(pets_csv))
    spec = normalise_spec(database, {"table": "pets", "columns": ["is_good", "name"]})
    rows = fetch_rows(database, spec)
    assert rows[0] == ["Yes", "Rex"]
    assert rows[2] == ["No", "Shadow"]


def test_export_report_writes_a_pdf_and_paginates(database, pets_csv: Path, sandbox: Path):
    pytest.importorskip("PySide6")
    import_spreadsheet(database, str(pets_csv))
    result = export_report(database, {"table": "pets", "title": "My pets"}, str(sandbox / "pets"))
    assert result["file"].endswith("pets.pdf")
    assert result["pages"] == 1
    assert result["rows_written"] == 4
    data = Path(result["file"]).read_bytes()
    assert data.startswith(b"%PDF")

    with pytest.raises(JubakoError, match="already a file"):
        export_report(database, {"table": "pets"}, str(sandbox / "pets.pdf"))
    again = export_report(database, {"table": "pets"}, str(sandbox / "pets.pdf"), overwrite=True)
    assert again["replaced_existing_file"] is True

    database.create_table("many", [Field("n", "integer", "N"), Field("words", "text", "Words")])
    for i in range(120):
        database.add_row("many", {"n": i, "words": "long text that has to wrap onto more lines " * 4})
    landscape = export_report(
        database, {"table": "many", "orientation": "landscape", "page_size": "a4"}, str(sandbox / "many.pdf")
    )
    assert landscape["pages"] > 1
    assert landscape["orientation"] == "landscape"


def test_export_report_refuses_paths_outside_roots(database, pets_csv: Path):
    import_spreadsheet(database, str(pets_csv))
    with pytest.raises(JubakoError, match="outside"):
        export_report(database, {"table": "pets"}, "/etc/pets.pdf")


def test_forms_are_remembered_in_the_database(database, pets_csv: Path):
    import_spreadsheet(database, str(pets_csv))
    plain = form_for(database, "pets")
    assert plain["saved"] is False
    assert plain["fields"] == ["name", "age", "adopted_on", "is_good", "weight_kg"]

    saved = save_form(database, "pets", {"title": "A pet", "fields": ["name", "is_good"], "labels": {"is_good": "Good pet?"}})
    assert saved["labels"]["is_good"] == "Good pet?"
    form = form_for(database, "pets")
    assert form["saved"] is True
    assert form["title"] == "A pet"
    # Fields left out of the saved order still show, after the chosen ones.
    assert form["fields"] == ["name", "is_good", "age", "adopted_on", "weight_kg"]
    assert form["labels"]["is_good"] == "Good pet?"
    with pytest.raises(BadName):
        save_form(database, "pets", {"fields": ["nope"]})


def test_reports_are_remembered_and_listed(database, pets_csv: Path):
    import_spreadsheet(database, str(pets_csv))
    assert list_reports(database) == []
    save_report(database, {"name": "Good pets", "table": "pets", "columns": ["name", "is_good"]})
    save_report(database, {"table": "pets", "title": "Everything"})
    names = [r["name"] for r in list_reports(database)]
    assert names == ["Everything", "Good pets"]
    assert load_report(database, "Good pets")["columns"] == ["name", "is_good"]
    assert delete_report(database, "Good pets") is True
    assert delete_report(database, "Good pets") is False
    assert [r["name"] for r in list_reports(database)] == ["Everything"]


def test_the_printer_path_paints_the_same_pages(database, pets_csv: Path, sandbox: Path):
    """`print_to` is what the system print dialog hands a QPrinter to."""
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtPrintSupport import QPrinter

    from jubako.printing import ReportDocument, ensure_gui_app
    from jubako.reports import fetch_rows, normalise_spec

    ensure_gui_app()
    import_spreadsheet(database, str(pets_csv))
    spec = normalise_spec(database, {"table": "pets", "orientation": "landscape"})
    document = ReportDocument(spec, fetch_rows(database, spec))
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(sandbox / "printed.pdf"))
    assert document.print_to(printer) == 1
    assert (sandbox / "printed.pdf").read_bytes().startswith(b"%PDF")
    preview = document.preview_image(0, 300)
    assert preview.width() == 300
    assert preview.width() > preview.height()  # landscape


def test_cell_text_drops_the_trailing_point_zero_on_whole_numbers():
    from jubako.reports import cell_text

    assert cell_text(3350.0, "real") == "3350"
    assert cell_text(42.5, "real") == "42.5"
    assert cell_text(7, "integer") == "7"
    assert cell_text(True, "boolean") == "Yes"
    assert cell_text(None, "real") == ""


# -- sorting, groups, totals, header and footer, saved views ------------------------

@pytest.fixture
def shop(database):
    database.create_table("orders", [
        Field("item"), Field("kind"), Field("qty", "integer"), Field("price", "real"), Field("paid", "boolean"),
    ])
    for row in [
        ("Bell", "Parts", 2, 4.5, True),
        ("Bike", "Bikes", 1, 300.0, False),
        ("Tube", "Parts", 5, 6.25, True),
        ("Trike", "Bikes", 1, 450.0, True),
        ("Gift card", None, 1, 20.0, False),
    ]:
        database.add_row("orders", dict(zip(["item", "kind", "qty", "price", "paid"], row)))
    return database


def test_report_sorts_its_rows(shop):
    spec = normalise_spec(shop, {"table": "orders", "columns": ["item", "price"],
                                 "sort": [{"field": "price", "descending": True}]})
    assert [row[0] for row in fetch_rows(shop, spec)] == ["Trike", "Bike", "Gift card", "Tube", "Bell"]
    assert spec["sort_words"] == "Price, highest first"


def test_report_groups_counts_and_totals(shop):
    from jubako.reports import fetch_lines

    spec = normalise_spec(shop, {"table": "orders", "columns": ["item", "qty", "price"], "group_by": "kind",
                                 "sort": [{"field": "item"}], "totals": {"qty": "sum", "price": "average"}})
    assert spec["show_count"] is True          # grouping counts rows unless told not to
    lines = fetch_lines(shop, spec)
    kinds = [line["kind"] for line in lines]
    # Blank kind sorts last, like everywhere else.
    assert kinds == ["group", "row", "row", "subtotal", "group", "row", "row", "subtotal",
                     "group", "row", "subtotal", "total"]
    assert lines[0] == {"kind": "group", "text": "Kind: Bikes", "count": "2 rows"}
    assert [line["cells"][0] for line in lines if line["kind"] == "row"] == ["Bike", "Trike", "Bell", "Tube", "Gift card"]
    assert lines[3]["cells"] == ["", "2", "avg 375"]
    assert lines[3]["label"] == "Totals"
    assert lines[8]["text"] == "Kind: (blank)"
    assert lines[-1] == {"kind": "total", "cells": ["", "10", "avg 156.15"], "label": "All rows · Totals · 5 rows"}


def test_report_totals_without_groups(shop):
    from jubako.reports import fetch_lines

    spec = normalise_spec(shop, {"table": "orders", "columns": ["item", "price"], "totals": {"price": "sum"},
                                 "filter": {"field": "paid", "op": "is", "value": "yes"}})
    lines = fetch_lines(shop, spec)
    assert [line["kind"] for line in lines] == ["row", "row", "row", "total"]
    assert lines[-1] == {"kind": "total", "cells": ["", "460.75"], "label": "Total"}
    counted = normalise_spec(shop, {"table": "orders", "columns": ["item"], "show_count": True})
    assert fetch_lines(shop, counted)[-1] == {"kind": "total", "cells": [""], "label": "5 rows"}


def test_report_totals_are_checked(shop):
    with pytest.raises(JubakoError, match="Only number columns"):
        normalise_spec(shop, {"table": "orders", "totals": {"item": "sum"}})
    with pytest.raises(JubakoError, match="sum or its average"):
        normalise_spec(shop, {"table": "orders", "totals": {"qty": "median"}})
    with pytest.raises(BadName):
        normalise_spec(shop, {"table": "orders", "group_by": "colour"})
    # A total on a column the report does not print is left out.
    assert normalise_spec(shop, {"table": "orders", "columns": ["item"], "totals": {"qty": "sum"}})["totals"] == {}


def test_report_uses_a_saved_view_and_follows_it(shop):
    from jubako import views

    views.save_view(shop, "orders", "Unpaid", {"field": "paid", "op": "is", "value": "no"},
                    sort=[{"field": "price", "descending": True}])
    spec = normalise_spec(shop, {"table": "orders", "columns": ["item"], "view": "Unpaid",
                                 "filter": {"field": "qty", "op": "more_than", "value": 100}})
    assert spec["filter_words"] == "Paid is No"          # the view wins over a filter given alongside
    assert [row[0] for row in fetch_rows(shop, spec)] == ["Bike", "Gift card"]
    save_report(shop, {**spec, "name": "Chase up"})
    views.rename_view(shop, "orders", "Unpaid", "Not paid")
    assert load_report(shop, "Chase up")["view"] == "Not paid"
    # Deleting the view keeps the report printing the same rows.
    views.delete_view(shop, "orders", "Not paid")
    kept = load_report(shop, "Chase up")
    assert kept["view"] == ""
    assert [row[0] for row in fetch_rows(shop, normalise_spec(shop, kept))] == ["Bike", "Gift card"]
    with pytest.raises(JubakoError, match="not there any more"):
        normalise_spec(shop, {"table": "orders", "view": "Nope"})


def test_report_header_footer_and_pdf_with_groups(shop, sandbox):
    pytest.importorskip("PySide6")
    from jubako.printing import ReportDocument
    from jubako.reports import fetch_lines

    spec = normalise_spec(shop, {"table": "orders", "group_by": "kind", "totals": {"price": "sum"},
                                 "header_text": "Nine Point Bikes", "footer_text": "Internal",
                                 "show_row_numbers": True})
    assert spec["header_text"] == "Nine Point Bikes" and spec["footer_text"] == "Internal"
    document = ReportDocument(spec, lines=fetch_lines(shop, spec))
    assert document.row_count == 5
    # Row numbers count rows only, straight through the groups.
    assert [row[0] for row in document.rows] == ["1", "2", "3", "4", "5"]
    assert document.page_count == 1
    assert not document.preview_image(0, 400).isNull()
    result = export_report(shop, spec, str(sandbox / "grouped.pdf"))
    assert result["rows_written"] == 5 and Path(result["file"]).stat().st_size > 1000


def test_a_long_grouped_report_never_leaves_a_heading_alone(database):
    pytest.importorskip("PySide6")
    from jubako.printing import ReportDocument
    from jubako.reports import fetch_lines

    database.create_table("many", [Field("team"), Field("who")])
    for i in range(400):
        database.add_row("many", {"team": f"Team {i // 7:02d}", "who": f"Person {i}"})
    spec = normalise_spec(database, {"table": "many", "group_by": "team"})
    document = ReportDocument(spec, lines=fetch_lines(database, spec))
    assert document.page_count > 3
    for start, end in document.pages:
        assert document.lines[end - 1]["kind"] != "group" or end == len(document.lines)


def test_report_follows_field_renames_and_drops(shop):
    from jubako import schema

    save_report(shop, {"name": "By kind", "table": "orders", "columns": ["item", "qty", "kind"], "group_by": "kind",
                       "sort": [{"field": "qty"}], "totals": {"qty": "sum"},
                       "filter": {"field": "paid", "op": "is", "value": "yes"}})
    schema.rename_field(shop, "orders", "qty", "quantity")
    kept = load_report(shop, "By kind")
    assert kept["columns"] == ["item", "quantity", "kind"]
    assert kept["sort"] == [{"field": "quantity", "descending": False}]
    assert kept["totals"] == {"quantity": "sum"}
    schema.rename_field(shop, "orders", "kind", "category")
    assert load_report(shop, "By kind")["group_by"] == "category"
    schema.drop_field(shop, "orders", "category")
    kept = load_report(shop, "By kind")
    assert kept["group_by"] == "" and kept["columns"] == ["item", "quantity"]
    schema.drop_field(shop, "orders", "paid")
    kept = load_report(shop, "By kind")
    assert kept["filter"] is None and kept["totals"] == {"quantity": "sum"}


def test_a_form_can_hide_fields_and_they_keep_their_values(database, pets_csv):
    from jubako import schema
    from jubako.reports import reset_form

    import_spreadsheet(database, str(pets_csv))
    saved = save_form(database, "pets", {"title": "Pet card", "fields": ["age", "name"], "hidden": ["weight_kg"],
                                         "labels": {"age": "Years"}})
    assert saved["fields"] == ["age", "name", "adopted_on", "is_good", "weight_kg"]   # every field has a place
    form = form_for(database, "pets")
    assert form["fields"] == ["age", "name", "adopted_on", "is_good"]
    assert form["order"][-1] == "weight_kg" and form["hidden"] == ["weight_kg"]
    assert form["labels"]["age"] == "Years" and form["title"] == "Pet card"
    with pytest.raises(JubakoError, match="at least one field"):
        save_form(database, "pets", {"hidden": ["name", "age", "adopted_on", "is_good", "weight_kg"]})
    with pytest.raises(BadName):
        save_form(database, "pets", {"hidden": ["colour"]})
    # A hidden field follows a rename, and leaves with a drop.
    schema.rename_field(database, "pets", "weight_kg", "weight")
    assert form_for(database, "pets")["hidden"] == ["weight"]
    schema.drop_field(database, "pets", "weight")
    assert form_for(database, "pets")["hidden"] == []
    assert reset_form(database, "pets") is True
    assert form_for(database, "pets")["saved"] is False
    assert reset_form(database, "pets") is False
