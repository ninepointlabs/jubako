"""Spreadsheet in, table out, CSV back again."""

from __future__ import annotations

from pathlib import Path

import pytest

from jubako.errors import ImportProblem, JubakoError, PathNotAllowed
from jubako.exporter import export_table
from jubako.fields import BOOLEAN, DATE, INTEGER, REAL, TEXT
from jubako.importer import import_spreadsheet, plan_import


def test_plan_reports_what_would_happen(pets_csv: Path):
    plan = plan_import(str(pets_csv))
    assert plan["table"] == "pets"
    assert [field["type"] for field in plan["fields"]] == [TEXT, INTEGER, DATE, BOOLEAN, REAL]
    assert plan["fields"][2]["label"] == "adopted_on"


def test_import_creates_the_table_and_rows(database, pets_csv: Path):
    report = import_spreadsheet(database, str(pets_csv))
    assert report["table"] == "pets"
    assert report["rows_added"] == 4
    assert report["note_count"] == 0

    page = database.list_rows("pets")
    assert page["total"] == 4
    assert page["rows"][0][1] == "Rex"
    assert page["rows"][0][2] == 4
    assert page["rows"][0][3] == "2021-03-14"
    assert page["rows"][0][4] is True  # "yes" comes back as a real yes
    assert page["rows"][3][2] is None  # the blank age stays blank, not zero


def test_importing_twice_is_refused_unless_asked(database, pets_csv: Path):
    import_spreadsheet(database, str(pets_csv))
    with pytest.raises(JubakoError):
        import_spreadsheet(database, str(pets_csv))
    report = import_spreadsheet(database, str(pets_csv), if_exists="replace")
    assert report["rows_added"] == 4
    assert database.count_rows("pets") == 4


def test_a_formula_is_kept_as_text_not_worked_out(database, sandbox: Path):
    sheet = sandbox / "sums.csv"
    sheet.write_text('label,amount\nrent,"=1+1"\n', "utf-8")
    import_spreadsheet(database, str(sheet))
    assert database.list_rows("sums")["rows"][0][2] == "=1+1"


def test_odd_headings_become_safe_fields(database, sandbox: Path):
    sheet = sandbox / "odd.csv"
    sheet.write_text("First Name,First Name,2024 Total ($)\nAda,Lovelace,10\n", "utf-8")
    report = import_spreadsheet(database, str(sheet))
    assert [f["name"] for f in report["created_fields"]] == [
        "first_name",
        "first_name_2",
        "c_2024_total",
    ]


def test_a_stray_cell_is_kept_as_words_and_reported(database, sandbox: Path):
    sheet = sandbox / "ages.csv"
    # The first 500 rows decide the type; a later odd value must not be lost.
    lines = ["age"] + [str(n) for n in range(600)] + ["unknown"]
    sheet.write_text("\n".join(lines) + "\n", "utf-8")
    report = import_spreadsheet(database, str(sheet))
    assert report["note_count"] == 1
    assert "unknown" in report["notes"][0]
    assert report["rows_added"] == 601


def test_semicolon_files_are_read(database, sandbox: Path):
    sheet = sandbox / "euro.csv"
    sheet.write_text("name;count\nAda;3\nGrace;4\n", "utf-8")
    report = import_spreadsheet(database, str(sheet))
    assert report["rows_added"] == 2
    assert [f["name"] for f in report["created_fields"]] == ["name", "count"]


def test_empty_file_is_reported_kindly(database, sandbox: Path):
    sheet = sandbox / "empty.csv"
    sheet.write_text("", "utf-8")
    with pytest.raises(ImportProblem):
        import_spreadsheet(database, str(sheet))


def test_a_broken_excel_file_is_refused_in_words(database, sandbox: Path):
    pytest.importorskip("openpyxl")
    sheet = sandbox / "book.xlsx"
    sheet.write_bytes(b"PK\x03\x04not really a workbook")
    with pytest.raises(ImportProblem, match="Excel"):
        import_spreadsheet(database, str(sheet))


def test_old_xls_is_refused_with_advice(database, sandbox: Path):
    sheet = sandbox / "book.xls"
    sheet.write_bytes(b"\xd0\xcf\x11\xe0 old excel")
    with pytest.raises(ImportProblem, match="save it as .xlsx"):
        import_spreadsheet(database, str(sheet))


def test_xlsx_round_trip_keeps_types(database, pets_csv: Path, sandbox: Path):
    pytest.importorskip("openpyxl")
    import_spreadsheet(database, str(pets_csv))
    out = export_table(database, "pets", str(sandbox / "pets.xlsx"), file_format="xlsx")
    assert out["format"] == "xlsx"
    assert out["rows_written"] == 4
    assert (sandbox / "pets.xlsx").exists()

    plan = plan_import(str(sandbox / "pets.xlsx"))
    assert plan["sheets"] == ["pets"]
    assert plan["sheet"] == "pets"
    assert [f["type"] for f in plan["fields"]] == ["text", "integer", "date", "boolean", "real"]

    back = import_spreadsheet(database, str(sandbox / "pets.xlsx"), table="pets_again")
    assert back["rows_added"] == 4
    rows = database.list_rows("pets_again")["rows"]
    assert rows[0][1:] == ["Rex", 4, "2021-03-14", True, 12.5]


def test_xlsx_import_picks_a_sheet_and_reads_saved_formula_values(database, sandbox: Path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    first = book.active
    first.title = "People"
    first.append(["Name", "Age"])
    first.append(["Ann", 31])
    second = book.create_sheet("Totals")
    second.append(["Item", "Price", "Doubled"])
    second.append(["Pen", 1.5, "=B2*2"])
    book.save(sandbox / "two.xlsx")

    plan = plan_import(str(sandbox / "two.xlsx"))
    assert plan["sheets"] == ["People", "Totals"]
    assert plan["table"] == "people"
    result = import_spreadsheet(database, str(sandbox / "two.xlsx"), sheet="Totals")
    assert result["table"] == "totals"
    # openpyxl wrote no cached value for the formula, so the cell is blank —
    # the formula itself is never worked out by Jubako.
    rows = database.list_rows("totals")["rows"]
    assert rows[0][1:3] == ["Pen", 1.5]
    assert rows[0][3] is None
    with pytest.raises(ImportProblem, match="no sheet called"):
        import_spreadsheet(database, str(sandbox / "two.xlsx"), sheet="Nope")


def test_import_refuses_a_file_outside_the_approved_roots(database):
    with pytest.raises(PathNotAllowed):
        import_spreadsheet(database, "/etc/passwd")


def test_export_writes_every_row(database, pets_csv: Path, sandbox: Path):
    import_spreadsheet(database, str(pets_csv))
    out = sandbox / "out.csv"
    report = export_table(database, "pets", str(out))
    assert report["rows_written"] == 4
    lines = out.read_text("utf-8").strip().splitlines()
    assert lines[0] == "name,age,adopted_on,is_good,weight_kg"
    assert lines[1] == "Rex,4,2021-03-14,yes,12.5"
    assert lines[3].split(",")[3] == "no"
    assert len(lines) == 5


def test_export_will_not_clobber_without_permission(database, pets_csv: Path, sandbox: Path):
    import_spreadsheet(database, str(pets_csv))
    out = sandbox / "out.csv"
    out.write_text("keep me", "utf-8")
    with pytest.raises(JubakoError):
        export_table(database, "pets", str(out))
    report = export_table(database, "pets", str(out), overwrite=True)
    assert report["replaced_existing_file"] is True


def test_export_refuses_a_path_outside_the_roots(database, pets_csv: Path):
    import_spreadsheet(database, str(pets_csv))
    with pytest.raises(PathNotAllowed):
        export_table(database, "pets", "/etc/jubako-escape.csv")


def test_unknown_export_format_is_refused(database, pets_csv: Path, sandbox: Path):
    import_spreadsheet(database, str(pets_csv))
    with pytest.raises(JubakoError, match="cannot write"):
        export_table(database, "pets", str(sandbox / "out.doc"), file_format="doc")


def test_the_report_says_when_a_table_was_replaced(database, pets_csv: Path):
    first = import_spreadsheet(database, str(pets_csv))
    assert first["replaced_existing"] is False
    second = import_spreadsheet(database, str(pets_csv), if_exists="replace")
    assert second["replaced_existing"] is True


def _titled_workbook(path: Path, *, with_table: bool) -> None:
    """A normal titled Excel list: title in A1, subtitle, two blank rows, then 15 headers."""
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl.worksheet.table import Table

    headers = ["IDN", "First Name", "Middle / Nickname", "Last Name", "Mail Status", "Address Line 1",
               "City", "State", "ZIP", "Home Phone", "Work Phone", "Cell Phone", "Email", "Record Type", "Notes"]
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Consolidated List"
    sheet["A1"] = "Tyler Community Consolidated List"
    sheet["A2"] = "32 records — updated this week"
    sheet.append([])
    sheet.append([])
    sheet.append(headers)
    sheet.append([190597, "Haleigh", "D", "Arent", "Good", "914 Joel Dr", "Tyler", "TX", "75703-4844", "308-532-6987", None, None, None, "Adult", "Dial number"])
    sheet.append([255062, "Keondra", None, "Bailey", "Returned", "1603 Merrill", "Tyler", "TX", "75701", None, None, "817-902-2481", "k@example.com", "Adult", "Voicemail"])
    sheet.append([300100, "Casey", "T", "Collier", "Good", "1 Main St", "Tyler", "TX", "75702", "903-617-0493", None, None, None, "Youth", None])
    if with_table:
        sheet.add_table(Table(displayName="ConsolidatedMembers", ref="A5:O8"))
        # Junk outside the Table must not become part of the import.
        sheet["A10"] = "Printed by"
        sheet["B10"] = "Somebody"
        sheet["A11"] = "Total"
        sheet["B11"] = 3
    book.save(path)


def test_xlsx_title_rows_are_not_mistaken_for_headers(database, sandbox: Path):
    _titled_workbook(sandbox / "titled.xlsx", with_table=False)
    plan = plan_import(str(sandbox / "titled.xlsx"))
    labels = [f["label"] for f in plan["fields"]]
    assert len(labels) == 15
    assert labels[:4] == ["IDN", "First Name", "Middle / Nickname", "Last Name"]
    assert labels[-1] == "Notes"
    assert "Tyler Community Consolidated List" not in labels
    result = import_spreadsheet(database, str(sandbox / "titled.xlsx"))
    assert result["rows_added"] == 3
    rows = database.list_rows("titled")["rows"]
    assert rows[0][2] == "Haleigh"
    assert rows[1][13] == "k@example.com"


def test_xlsx_prefers_the_excel_table_and_ignores_cells_outside_it(database, sandbox: Path):
    _titled_workbook(sandbox / "tabled.xlsx", with_table=True)
    plan = plan_import(str(sandbox / "tabled.xlsx"))
    assert len(plan["fields"]) == 15
    assert plan["fields"][1]["label"] == "First Name"
    result = import_spreadsheet(database, str(sandbox / "tabled.xlsx"))
    assert result["rows_added"] == 3  # not the "Printed by" / "Total" rows below the Table
    names = [row[2] for row in database.list_rows("tabled")["rows"]]
    assert names == ["Haleigh", "Keondra", "Casey"]


def test_xlsx_one_column_sheet_still_imports(database, sandbox: Path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Name"])
    sheet.append(["Ann"])
    sheet.append(["Bob"])
    book.save(sandbox / "one.xlsx")
    plan = plan_import(str(sandbox / "one.xlsx"))
    assert [f["label"] for f in plan["fields"]] == ["Name"]
    assert import_spreadsheet(database, str(sandbox / "one.xlsx"))["rows_added"] == 2


def test_xlsx_columns_with_data_but_no_heading_are_kept(database, sandbox: Path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Name", None, "Age"])
    sheet.append(["Ann", "left-handed", 31])
    sheet.append(["Bob", None, 45, "spills into a fourth column"])
    book.save(sandbox / "gaps.xlsx")
    plan = plan_import(str(sandbox / "gaps.xlsx"))
    assert [f["label"] for f in plan["fields"]] == ["Name", "Column 2", "Age", "Column 4"]
    import_spreadsheet(database, str(sandbox / "gaps.xlsx"))
    rows = database.list_rows("gaps")["rows"]
    assert rows[0][1:] == ["Ann", "left-handed", 31, None]
    assert rows[1][4] == "spills into a fourth column"


def test_a_ragged_csv_warns_with_line_numbers(database, sandbox):
    target = sandbox / "ragged.csv"
    target.write_text('a,b\n1,1,2\n2,"unclosed,4\n3,x\n', encoding="utf-8")
    result = import_spreadsheet(database, str(target))
    assert result["warning_count"] == 2
    assert result["warnings"][0].startswith("Line 2: 3 values but 2 columns")
    assert result["warnings"][1].startswith("Line 3: a quote is never closed")


def test_a_tidy_csv_has_no_warnings(database, sandbox):
    target = sandbox / "tidy.csv"
    target.write_text('a,b\n1,"two, quoted"\n2,"multi\nline"\n', encoding="utf-8")
    assert import_spreadsheet(database, str(target))["warnings"] == []
