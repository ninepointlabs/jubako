"""The MCP server, driven the way an agent drives it: JSON-RPC over a pipe."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jubako_mcp import server


def call(name: str, **arguments):
    """Run one tool and hand back the parsed payload."""
    result = server.call_tool(name, arguments)
    payload = json.loads(result["content"][0]["text"])
    return payload, result["isError"]


def test_every_tool_is_listed_with_a_schema():
    names = {tool["name"] for tool in server.TOOL_SCHEMAS}
    assert {
        "create_database",
        "list_databases",
        "open_database",
        "import_spreadsheet",
        "list_tables",
        "describe_table",
        "list_rows",
        "add_row",
        "export_table",
    } <= names
    for tool in server.TOOL_SCHEMAS:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_the_whole_job_end_to_end(sandbox: Path, pets_csv: Path):
    path = str(sandbox / "pets.jubadb")

    made, failed = call("create_database", title="Pets", backend="sqlite", path=path)
    assert not failed and made["made"] is True

    imported, failed = call("import_spreadsheet", path=path, file=str(pets_csv))
    assert not failed
    assert imported["table"] == "pets"
    assert imported["rows_added"] == 4

    tables, failed = call("list_tables", path=path)
    assert not failed
    assert tables["tables"] == [{"name": "pets", "fields": 5, "rows": 4}]

    described, failed = call("describe_table", path=path, table="pets")
    assert [f["type"] for f in described["fields"]] == [
        "text",
        "integer",
        "date",
        "boolean",
        "real",
    ]

    rows, failed = call("list_rows", path=path, table="pets", limit=2)
    assert not failed
    assert len(rows["rows"]) == 2
    assert rows["total"] == 4

    added, failed = call("add_row", path=path, table="pets", values={"name": "Nala", "age": 3})
    assert not failed and added["id"] == 5

    out = str(sandbox / "pets-out.csv")
    exported, failed = call("export_table", path=path, table="pets", file=out)
    assert not failed and exported["rows_written"] == 5
    assert Path(out).exists()

    listed, failed = call("list_databases")
    assert not failed and listed["count"] >= 1
    assert listed["databases"][0]["title"] == "Pets"


def test_paths_outside_the_roots_come_back_as_a_clean_error(sandbox: Path):
    payload, failed = call("create_database", title="Nope", path="/etc/jubako.jubadb")
    assert failed is True
    assert "outside the folders" in payload["error"]

    path = str(sandbox / "ok.jubadb")
    call("create_database", title="Ok", path=path)
    payload, failed = call("import_spreadsheet", path=path, file="../../etc/passwd")
    assert failed is True
    assert "error" in payload


def test_an_argument_a_tool_does_not_take_is_refused_before_anything_happens(sandbox: Path, pets_csv: Path):
    path = str(sandbox / "pets.jubadb")
    call("create_database", title="Pets", path=path)
    call("import_spreadsheet", path=path, file=str(pets_csv), table="pets")
    before = call("list_rows", path=path, table="pets")[0]["rows"]

    # "where" for "filter" would otherwise read every row as if it were filtered.
    payload, failed = call("list_rows", path=path, table="pets", where={"field": "name", "op": "is", "value": "Rex"})
    assert failed is True
    assert "does not take the argument 'where' (did you mean 'filter'?)" in payload["error"]

    payload, failed = call("update_rows", path=path, table="pets", filtr={"field": "name", "op": "is", "value": "Rex"},
                           values={"name": "Max"}, every_row=True)
    assert failed is True
    assert "'filtr' (did you mean 'filter'?)" in payload["error"] and "Nothing was done" in payload["error"]
    assert call("list_rows", path=path, table="pets")[0]["rows"] == before

    payload, failed = call("list_tables", path=path, colour="red", size=2)
    assert failed is True and "arguments 'colour', 'size'" in payload["error"]


def test_overwrite_is_reported(sandbox: Path, pets_csv: Path):
    path = str(sandbox / "pets.jubadb")
    call("create_database", title="Pets", path=path)
    call("import_spreadsheet", path=path, file=str(pets_csv))
    out = str(sandbox / "out.csv")
    call("export_table", path=path, table="pets", file=out)
    payload, failed = call("export_table", path=path, table="pets", file=out)
    assert failed is True
    payload, failed = call("export_table", path=path, table="pets", file=out, overwrite=True)
    assert not failed
    assert payload["note"] == "A file was already there and has been replaced."


def test_an_unknown_tool_is_an_error_not_a_crash():
    payload, failed = call("delete_everything")
    assert failed is True
    assert "no tool called" in payload["error"]


def test_backends_are_listed_with_their_driver_state():
    payload, failed = call("list_backends")
    assert not failed
    assert [b["key"] for b in payload["backends"]] == ["sqlite", "postgres", "mysql"]
    assert payload["default"] == "sqlite"
    assert payload["backends"][0]["driver_installed"] is True


def test_handshake_over_the_wire(sandbox: Path, pets_csv: Path):
    """Start the server as a real process and talk MCP to it."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "create_database",
                "arguments": {"title": "Wire", "path": str(sandbox / "wire.jubadb")},
            },
        },
    ]
    source = "\n".join(json.dumps(request) for request in requests) + "\n"
    process = subprocess.run(
        [sys.executable, "-m", "jubako_mcp"],
        input=source,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=_env(sandbox),
    )
    assert process.returncode == 0, process.stderr
    replies = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert replies[0]["result"]["serverInfo"]["name"] == "jubako"
    assert replies[0]["result"]["protocolVersion"] == server.PROTOCOL_VERSION
    assert len(replies[1]["result"]["tools"]) == len(server.TOOL_SCHEMAS)
    assert replies[2]["result"]["isError"] is False
    assert (sandbox / "wire.jubadb").exists()


def test_bad_json_does_not_stop_the_server():
    out = io.StringIO()
    server.serve(io.StringIO('not json\n{"jsonrpc":"2.0","id":9,"method":"ping"}\n'), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 9


def _env(sandbox: Path) -> dict:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["JUBAKO_ROOTS"] = str(sandbox)
    env["XDG_STATE_HOME"] = str(sandbox / "state")
    return env


def test_row_form_and_report_tools(sandbox, pets_csv):
    pytest.importorskip("PySide6")
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "mcp.jubadb")
    HANDLERS["create_database"]({"title": "Pets", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})
    rows = HANDLERS["list_rows"]({"path": db, "table": "pets"})
    first = rows["rows"][0][0]

    changed = HANDLERS["update_row"]({"path": db, "table": "pets", "id": first, "values": {"age": 5}})
    assert changed["updated"] is True
    assert HANDLERS["list_rows"]({"path": db, "table": "pets"})["rows"][0][2] == 5

    gone = HANDLERS["delete_row"]({"path": db, "table": "pets", "id": first})
    assert gone["deleted"] is True
    assert HANDLERS["delete_row"]({"path": db, "table": "pets", "id": first})["deleted"] is False
    assert HANDLERS["list_rows"]({"path": db, "table": "pets"})["total"] == 3

    form = HANDLERS["create_form"]({"path": db, "table": "pets", "fields": ["name", "is_good"], "labels": {"is_good": "Good?"}})
    assert form["form"]["labels"]["is_good"] == "Good?"
    assert HANDLERS["get_form"]({"path": db, "table": "pets"})["fields"][:2] == ["name", "is_good"]

    kept = HANDLERS["create_report"]({"path": db, "name": "Names", "table": "pets", "columns": ["name"], "orientation": "landscape"})
    assert kept["report"]["orientation"] == "landscape"
    assert [r["name"] for r in HANDLERS["list_reports"]({"path": db})["reports"]] == ["Names"]

    out = HANDLERS["export_report"]({"path": db, "name": "Names", "file": str(sandbox / "names.pdf")})
    assert out["pages"] == 1
    assert out["file"].endswith("names.pdf")
    direct = HANDLERS["export_report"]({"path": db, "table": "pets", "title": "Quick", "file": str(sandbox / "quick.pdf")})
    assert direct["title"] == "Quick"
    assert HANDLERS["export_table"]({"path": db, "table": "pets", "file": str(sandbox / "t.pdf"), "format": "pdf"})["format"] == "pdf"
    assert HANDLERS["delete_report"]({"path": db, "name": "Names"})["deleted"] is True


def test_schema_tools_and_import_all_sheets(sandbox, pets_csv):
    openpyxl = pytest.importorskip("openpyxl")
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "schema.jubadb")
    HANDLERS["create_database"]({"title": "S", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})

    renamed = HANDLERS["rename_field"]({"path": db, "table": "pets", "field": "weight_kg", "new_name": "weight", "label": "Weight"})
    assert renamed["fields"][-1] == {"name": "weight", "type": "real", "label": "Weight"}
    relabelled = HANDLERS["rename_field"]({"path": db, "table": "pets", "field": "age", "label": "Years"})
    assert relabelled["fields"][1]["label"] == "Years"
    dropped = HANDLERS["delete_field"]({"path": db, "table": "pets", "field": "adopted_on"})
    assert dropped["deleted"] == "adopted_on"
    assert [f["name"] for f in dropped["fields"]] == ["name", "age", "is_good", "weight"]

    book = openpyxl.Workbook()
    a = book.active; a.title = "One"; a.append(["X"]); a.append([1])
    b = book.create_sheet("Two"); b.append(["Y"]); b.append([2])
    book.save(sandbox / "two.xlsx")
    result = HANDLERS["import_spreadsheet"]({"path": db, "file": str(sandbox / "two.xlsx"), "all_sheets": True})
    assert [t["table"] for t in result["tables"]] == ["one", "two"]
    single = HANDLERS["import_spreadsheet"]({"path": db, "file": str(sandbox / "two.xlsx"), "table": "just_one"})
    assert single["table"] == "just_one"

    gone = HANDLERS["delete_table"]({"path": db, "table": "two"})
    assert gone["deleted"] is True and gone["rows_deleted"] == 1
    assert "two" not in [t["name"] for t in HANDLERS["list_tables"]({"path": db})["tables"]]

    with pytest.raises(Exception, match="confirm"):
        HANDLERS["delete_database"]({"path": db, "confirm": False})
    assert (sandbox / "schema.jubadb").exists()
    assert HANDLERS["delete_database"]({"path": db, "confirm": True})["deleted"] is True
    assert not (sandbox / "schema.jubadb").exists()


def test_add_field_and_filtered_rows_and_report(sandbox, pets_csv):
    pytest.importorskip("PySide6")
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "filter.jubadb")
    HANDLERS["create_database"]({"title": "F", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})
    added = HANDLERS["add_field"]({"path": db, "table": "pets", "label": "Moved", "type": "boolean"})
    assert added["added"] == "moved"
    rows = HANDLERS["list_rows"]({"path": db, "table": "pets"})
    HANDLERS["update_row"]({"path": db, "table": "pets", "id": rows["rows"][0][0], "values": {"moved": "yes"}})
    kept = HANDLERS["list_rows"]({"path": db, "table": "pets", "filter": {"field": "moved", "op": "is_not", "value": "yes"}})
    assert [r[1] for r in kept["rows"]] == ["Milo", "Shadow", "Pip"]
    assert kept["total"] == 3 and kept["total_all"] == 4
    with pytest.raises(Exception, match="no field"):
        HANDLERS["list_rows"]({"path": db, "table": "pets", "filter": {"field": "gone", "op": "is", "value": 1}})
    out = HANDLERS["export_report"]({"path": db, "table": "pets", "file": str(sandbox / "kept.pdf"),
                                     "filter": {"field": "moved", "op": "is_not", "value": "yes"}})
    assert out["rows_written"] == 3
    saved = HANDLERS["create_report"]({"path": db, "name": "Still here", "table": "pets",
                                       "filter": {"field": "moved", "op": "empty"}})
    assert saved["report"]["filter_words"] == "Moved is empty"


def test_view_tools(sandbox, pets_csv):
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "views.jubadb")
    HANDLERS["create_database"]({"title": "V", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})
    HANDLERS["add_field"]({"path": db, "table": "pets", "label": "Moved", "type": "boolean"})
    saved = HANDLERS["save_view"]({"path": db, "table": "pets", "name": "Still here",
                                   "filter": {"field": "moved", "op": "is_not", "value": "yes"}, "default": True})
    assert saved["saved"] is True and saved["words"] == "Moved is not Yes"
    assert [v["name"] for v in HANDLERS["list_views"]({"path": db})["views"]] == ["Still here"]
    view = HANDLERS["get_view"]({"path": db, "table": "pets", "name": "Still here"})
    assert view["default"] is True
    rows = HANDLERS["list_rows"]({"path": db, "table": "pets", "filter": view["filter"]})
    assert rows["total"] == 4
    with pytest.raises(Exception, match="already a view"):
        HANDLERS["save_view"]({"path": db, "table": "pets", "name": "Still here", "filter": {"field": "moved", "op": "empty"}})
    assert HANDLERS["delete_view"]({"path": db, "table": "pets", "name": "Still here"})["deleted"] is True
    assert HANDLERS["list_views"]({"path": db, "table": "pets"})["views"] == []


def test_rules_and_sort_through_the_tools(sandbox, pets_csv):
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "rules.jubadb")
    HANDLERS["create_database"]({"title": "R", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})
    rows = HANDLERS["list_rows"]({
        "path": db, "table": "pets",
        "filter": {"match": "any", "rules": [{"field": "age", "op": "more_than", "value": 3},
                                             {"field": "adopted_on", "op": "after", "value": "2024-01-01"}]},
        "sort": [{"field": "name", "descending": True}],
    })
    assert [row[1] for row in rows["rows"]] == ["Shadow", "Rex", "Pip"]
    assert rows["sort"] == [{"field": "name", "descending": True}]
    saved = HANDLERS["save_view"]({"path": db, "table": "pets", "name": "Youngest", "sort": [{"field": "age"}]})
    assert saved["words"] == "sorted by age, lowest first" and saved["filter"] is None


def test_grouped_report_through_the_tools(sandbox, pets_csv):
    pytest.importorskip("PySide6")
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "grouped.jubadb")
    HANDLERS["create_database"]({"title": "G", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})
    kept = HANDLERS["create_report"]({"path": db, "table": "pets", "name": "By goodness", "group_by": "is_good",
                                      "totals": {"weight_kg": "sum"}, "sort": [{"field": "name"}],
                                      "header_text": "Vet list"})
    assert kept["report"]["group_by"] == "is_good" and kept["report"]["show_count"] is True
    result = HANDLERS["export_report"]({"path": db, "name": "By goodness", "file": str(sandbox / "g.pdf")})
    assert result["rows_written"] == 4


def test_templates_through_the_tools(sandbox):
    from jubako_mcp.server import HANDLERS

    assert "contacts" in [t["key"] for t in HANDLERS["list_templates"]({})["templates"]]
    made = HANDLERS["create_database"]({"title": "Stock", "path": str(sandbox / "stock.jubadb"), "template": "inventory"})
    assert made["template"]["tables"] == ["suppliers", "items"] and made["template"]["rows_added"] == 10
    assert made["template"]["opens"] == "items"
    with pytest.raises(Exception, match="no template"):
        HANDLERS["create_database"]({"title": "X", "path": str(sandbox / "x.jubadb"), "template": "nope"})
    assert not (sandbox / "x.jubadb").exists()


def test_unique_and_row_number_tools(sandbox):
    import sqlite3

    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "keys.jubadb")
    HANDLERS["create_database"]({"title": "K", "path": db})
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE birds (name TEXT)")
    connection.execute("INSERT INTO birds VALUES ('Wren'), ('Wren')")
    connection.commit()
    connection.close()
    described = HANDLERS["describe_table"]({"path": db, "table": "birds"})
    assert described["editable"] is False and "add_row_number" in described["note"]
    assert HANDLERS["add_row_number"]({"path": db, "table": "birds"})["rows"] == 2
    with pytest.raises(Exception, match="already repeats"):
        HANDLERS["set_unique"]({"path": db, "table": "birds", "field": "name"})
    added = HANDLERS["add_field"]({"path": db, "table": "birds", "label": "Ring", "unique": True})
    assert added["fields"][-1]["unique"] is True
    HANDLERS["update_row"]({"path": db, "table": "birds", "id": 1, "values": {"ring": "A1"}})
    with pytest.raises(Exception, match="Ring cannot repeat"):
        HANDLERS["update_row"]({"path": db, "table": "birds", "id": 2, "values": {"ring": "A1"}})
    assert HANDLERS["set_unique"]({"path": db, "table": "birds", "field": "ring", "unique": False})["fields"][-1] == {
        "name": "ring", "type": "text", "label": "Ring"}


def test_rename_and_copy_database_tools(sandbox, pets_csv):
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "orig.jubadb")
    HANDLERS["create_database"]({"title": "Orig", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})
    assert HANDLERS["rename_database"]({"path": db, "title": "Renamed"})["title"] == "Renamed"
    copied = HANDLERS["copy_database"]({"path": db, "file": str(sandbox / "copy.jubadb")})
    assert copied["replaced_existing_file"] is False
    assert HANDLERS["list_rows"]({"path": copied["file"], "table": "pets"})["total"] == 4


def test_bulk_row_tools(sandbox, pets_csv):
    from jubako_mcp.server import HANDLERS

    db = str(sandbox / "bulk.jubadb")
    HANDLERS["create_database"]({"title": "B", "path": db})
    HANDLERS["import_spreadsheet"]({"path": db, "file": str(pets_csv)})
    young = {"field": "age", "op": "less_than", "value": 5}
    assert HANDLERS["summarize_rows"]({"path": db, "table": "pets", "filter": young})["rows"] == 2
    assert HANDLERS["update_rows"]({"path": db, "table": "pets", "filter": young, "values": {"is_good": False}})["updated"] == 2
    with pytest.raises(Exception, match="every row"):
        HANDLERS["delete_rows"]({"path": db, "table": "pets"})
    assert HANDLERS["delete_rows"]({"path": db, "table": "pets", "filter": young})["deleted"] == 2
    assert HANDLERS["list_rows"]({"path": db, "table": "pets"})["total"] == 2
