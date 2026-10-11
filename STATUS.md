# Jubako — status

**Phase B (forms, Excel, reports, printing), then the Access features in `TODO.md`. Last updated 2026-10-10.**

## Fix 2026-10-10 — the remote smoke test runs again

`scripts/smoke_remote.py` made its table as `jubako_smoke_pets`, a name
Jubako keeps for itself, so it stopped at once ("Names starting with
'jubako_' are kept for Jubako itself."). The table is `smoke_pets` now.
Run against PostgreSQL 17 and MariaDB 11 (throwaway Docker containers):
OK on both, end to end.

## 2026-10-10 — Access features, part 3: the Database menu, forms, rows in bulk

`TODO.md` items 1–7 are all ticked now.

**3. Backstage.** The header's "Open another" became **Database…**: New
database, New from a template, Open another, Open a recent one, Save a
copy…, Rename…, Close, Delete this whole database (moved here from More…).
- **Save a copy** (`schema.save_copy`): SQLite's backup API into a `.part`
  file, then renamed, so the copy is whole even while the database is open;
  journal mode DELETE so it is one self-contained file. Refuses the
  database's own path, and a taken one unless overwrite (the window's save
  dialog asks). File databases only. Suggests "<name> copy <date>.jubadb".
- **Rename** (`schema.rename_database`): the title only; the file keeps its
  name; the recent list follows.
- CLI `jubako copy`, `jubako rename`; MCP `copy_database`, `rename_database`.

**5. Forms.** **Arrange…** on the form (and "Arrange the form…" in More…):
title, order (↑ ↓), "Show", and what each field is called on the form;
"Back to the plain form" forgets it. A saved form keeps every field's place
plus a `hidden` list; hidden fields keep their values (the form sends back
every value it loaded). Renames and drops follow into `hidden`. The form
shows its title next to "Row 3 of 7". **Duplicate** starts a new row from
the one on screen; no-repeats fields start blank, with a note. MCP
`create_form` takes `hidden`; `get_form` returns `order` and `hidden`.

**7b. The rows on screen, all at once.** In More…, for the rows the filter
shows ("These 12 rows") or every row ("All 40 rows"):
- **change a field** (yes / no picker for yes/no fields, "Make it blank
  instead"), with the count on the button;
- **delete them**, saying how many and, with no filter, that it is every row;
- **what they add up to**: per field how many are filled in; numbers total,
  average, lowest, highest; dates earliest and latest; yes/no how many Yes.
Core `update_matching` / `delete_matching` refuse "no filter" unless told
`every_row`; setting a no-repeats field is refused for more than one row,
and checked against the other rows for one. `summarize`. CLI `jubako set`,
`delete-rows` (both need `--all` without a filter), `summary`. MCP
`update_rows`, `delete_rows`, `summarize_rows` (36 tools now).

**Fixed on the way.** `apply_template` failed halfway when a view by the
same name was left over from an old table (the low-level
`Storage.drop_table` leaves views behind; `schema.drop_table` does not). A
template's views now replace such leftovers.

Verified live again on PostgreSQL 17 and MariaDB 11: summaries (including
yes counts), change and delete matching rows, no-repeats refused in bulk,
hidden form fields, renaming; save a copy refused for a server.

223 tests pass.

## 2026-10-10 — Access features, part 2: templates and keys

**4. Templates.** Five ready-made databases in `src/jubako/template_files/`
(JSON): Contacts, Inventory, Projects and tasks, Customer service, Home
collection. Each brings its tables, a few made-up example rows (optional),
saved views (one opens with the table), reports and forms.
`templates.apply_template` refuses a database that already has one of its
tables, before changing anything. Window: **Start from a template** on Home,
and "What should it start with?" in New database (with "Put in a few
made-up example rows"). CLI: `jubako templates`, `jubako new TITLE PATH
--template KEY [--empty]`. MCP: `list_templates`, `create_database` takes
`template` and `sample_rows`. An unknown key is refused before a file is
made. The wheel carries the JSON files (checked with `uv build`).

**2. Primary keys.**
- **No repeats.** A field can be unique: a checkbox per field in Fields, and
  in Add field. Turning it on is refused while values repeat, naming them
  ("Supplier already repeats …: “Northwind Cycle Supply” (3 rows) …"). A
  write that would repeat says which field and value, in words, before the
  engine is asked; if the engine refuses anyway it still comes back in
  words, and PostgreSQL's aborted transaction is rolled back. Follows field
  renames; dropping the field drops its index first (SQLite needs that).
  Not for yes/no fields. The Inventory template's SKU is unique.
  CLI `jubako unique PATH TABLE FIELD [--off]`; MCP `set_unique`,
  `add_field` `unique`. Field dicts only carry `"unique": true` when set, so
  existing shapes are unchanged.
- **Tables made elsewhere.** See "Row identity" below. CLI
  `jubako add-row-number`; MCP `add_row_number`; `describe_table` says
  `editable: false` for such a table.

**Bugs found on the way (existing, now fixed).**
- A table made outside Jubako with no `id`: SQLite read the quoted `"id"`
  as the string `'id'`, so every row's number was the word "id" and grid or
  form editing failed on `int('id')`. Now its row number is blank and
  editing is refused in words.
- **PostgreSQL: every yes/no filter failed** (`operator does not exist:
  boolean = smallint`): the filter sent 0/1 to every engine. Only SQLite
  gets 0/1 now.
- **MySQL / MariaDB: every "contains" filter failed** with a syntax error:
  `ESCAPE '\'` is unterminated in a MySQL string. The LIKE escape is now
  `!` on every engine.

**Verified live** against PostgreSQL 17 and MariaDB 11 (throwaway Docker
containers): sorting with blanks last, date and number comparisons, any/all
rules, starts with, yes/no filters, no-repeats (refusal in words, rollback,
rename, drop, refusing while values repeat), adding a row number to a table
made by hand, applying the Inventory template and laying out its reports.

Not fixed (out of scope): `scripts/smoke_remote.py` stops at once because
its table name `jubako_smoke_pets` starts with the reserved `jubako_`.

210 tests pass.

## 2026-10-10 — Access features, part 1: queries and reports

Working through `TODO.md` (the Access features worth having, items 1–7).

**7a. Queries on one table, still no SQL.**
- **More matches.** Numbers: is more than / less than / at least / at most.
  Dates: is after / before / on or after / on or before (same ops, date
  words). Words: starts with. The filter bar only offers the matches that
  fit the field's type (`filters.ops_for`, `Bridge.filterOpsFor`).
- **Several rules.** `+ Rule` adds a row; the second row's "and / or" sets
  how all rules combine. A filter is now one rule `{field, op, value}` or
  `{match: all|any, rules: [...]}` (at most 10); one rule is always stored in
  the old shape, so existing views read the same. × takes a rule off (and
  re-applies if a filter was on).
- **Sort.** Tap a column heading: up, down, off (▲/▼ in the heading, "sorted
  by …" in the status line). Blanks sort last on every engine
  (`ORDER BY (col IS NULL), col`), and the row number breaks ties.
  `list_rows(sort=[{field, descending}])`, up to 3 fields; `order_by` still works.
- **Views keep the sort.** A view is a filter and/or a sort. Field renames
  follow into rules and sorts; a dropped field deletes views whose rules use
  it, and only trims the sort of views that sorted by it.
- CLI: `--filter` can repeat, `--any`, `--sort FIELD[:desc]` on `rows`,
  `save-view` and `report`. MCP: `filter` takes `match`/`rules`; `sort` on
  `list_rows`, `save_view` and reports.

**6. Reports.**
- **Order, groups, totals.** Sort by a field; "A heading for each <field>"
  with a row count per group; per number column "Sum" or "Average", per group
  (subtotal) and for the report. "Say how many rows" adds counts (on by
  default when grouping). Blanks group as "(blank)", last.
- **Header and footer.** A small line on top of every page; the footer text
  replaces the title at the foot of each page.
- **From a saved view.** A report can name a view; it then follows the
  view's filter and sort. Renaming the view updates the report; deleting it
  copies the view's rules into the report so it prints the same rows. When
  the table is showing a view, Print report starts from it.
- Core: `reports.report_lines` turns rows into lines (group / row /
  subtotal / total); `ReportDocument(spec, lines=...)` paints lines, never
  leaves a group heading alone at the foot of a page, and numbers rows
  straight through groups. Field renames and drops follow into a report's
  sort, group, totals and filter.

**Test helper fix.** `tests/test_app.py::_load_window` made the `Report`
object without keeping a reference, so Python collected it and the window's
report dialog saw `null` (the "Cannot read property 'pageCount' of null"
warnings in test runs). It is now parented to the engine. The real app
(`main.py`) was not affected.

190 tests pass.

## Fix 2026-09-28 — theme palette, number text, form and filter bar

Found while taking new preview screenshots with a bigger demo database.

- **The window ignored the Omarchy palette.** Qt Quick's Fusion style takes
  its palette from the system colour scheme, not from the application
  palette `theme.py` sets, so dialogs, inputs and plain labels used Fusion's
  stock dark palette (grey dialogs on every theme; white text on light
  themes). `Main.qml` now binds the window palette to `Theme`, and
  `Theme.apply()` sets the colour-scheme hint from the theme's mode.
- **Whole numbers read "3350.0".** `reports.cell_text` (now shared by the
  grid and reports) drops the trailing ".0". CSV export is unchanged.
- **Form yes/no boxes sat mid-row.** The checkbox fills the row, so it lines
  up with the text fields.
- **The filter bar kept the last table's rule.** Moving to a table with no
  rule starts the bar fresh.

- **The Views… menu cut its rows short.** It now opens leftwards from its
  button at the right edge and widens to fit "Name · rule" (up to 640 px).
  The More… menu opens leftwards too.

Not a bug, noted for anyone scripting the window: without `app.exec()`,
`processEvents()` never runs `deleteLater()`, so old grid cells stay on
screen after a model reset. Send `QEvent.DeferredDelete` by hand.

166 tests pass.

## Fix 2026-09-22 — "It looks like we cannot add fields"

**What Tim hit.** He wanted a Moved (yes / no) field on his Tyler list and
could not add one from the window.

**What was wrong.** Two things. Add field was hard to find: the More… menu
said "Fields: rename or delete…" (no mention of Add), and the only Add
button sat in the footer of the Fields list. And when found, it opened a
`Dialog` nested inside the Fields `Dialog`; a modal inside a modal is
unreliable in Qt Quick (it can show behind its parent or not take focus).
The core and bridge were fine all along.

**What changed.**
- More… now has **Add field…** as its own item at the top, and the list
  item reads "Fields: add, rename or delete…".
- The Fields list starts with a big **Add field…** button and a one-line
  hint; the footer is just Done.
- The Add, Rename and Delete-field dialogs are their own components at page
  level (`AddFieldDialog.qml`, `RenameFieldDialog.qml`, and the delete
  confirm in `DatabasePage.qml`), parented on the window overlay, never
  inside another dialog. Opening one from the Fields list closes the list
  and brings it back when the dialog is done or cancelled.
- Every footer button in these dialogs has a `DialogButtonBox` role.

**How to add a field now.** Open the table → **More…** → **Add field…** →
type the label (the name inside fills in) → pick the type (Yes / No for
Moved) → **Add it**. Or More… → Fields… → Add field….

**Proved.** A new test drives the real QML objects: opens the dialog from
More…, types Moved, picks Yes / No, presses Add it, and checks the grid has
the column blank in every row; then the same from the Fields list, and a
duplicate refused in words with the dialog staying open. Run offscreen on a
copy of Tim's Tyler file: Moved added to `consolidated_list`, blank in all
25 rows, the saved view "Mail Status Good" untouched (screenshots
inspected). Tim's own file already had a `moved` yes / no field on
`consolidated_list` by the time this fix was made (16 fields, added 06:54),
so nothing was added to it; it was left as it is.

162 tests pass.

## 2026-09-22 (evening) — Saved views: named filters that stick

Tim's follow-up: a filter worth keeping should not have to be typed again.
A **view** is one table, one name, one "Show rows where…" rule, kept inside
the `.jubadb` under `view:<table>:<name>` in Jubako's own info table, so
it travels with the file and survives close and reopen.

**In the window.** The filter bar ends with **Views…** (it reads "View: Still
here" while a saved view is on). The menu lists this table's views with
their rule in words; pick one and it applies. Below a line: **Save view…**
(only when a filter is on) asks for a name, pre-filled with the current
view's name, plus "Open this table with this view"; saving under a taken
name asks "Replace the view?" first. **Rename…** and **Delete…** appear for
the view that is on; Delete confirms with "The rows stay. Only the saved
filter goes." With no views yet the menu says "No saved views yet — Apply a
filter, then Save view…". Editing the bar after loading a view detaches
from it (the button goes back to "Views…"); nothing is overwritten unless
you save again.

**Default view.** One view per table can be the one the table opens with.
It is applied the first time the table is shown after the database opens;
Clear then shows everything, and it is not forced again that session.

**When a field changes.** Renaming a field updates the views on it (and
their words); deleting the field deletes those views; deleting the table
deletes its views. A view that somehow points at a missing field is removed
with a message when picked.

**Core, MCP, CLI.** `jubako/views.py`: `save_view` (refuses a blank or
taken name, needs a real filter), `get_view`, `list_views`, `delete_view`,
`rename_view`, `default_view`; uses `filters.normalise_filter`, so there is
still one filter language. MCP (28 tools then): `list_views`, `get_view`,
`save_view` (`replace`, `default`), `delete_view`. CLI: `views`,
`save-view --filter FIELD OP [VALUE] [--default] [--replace]`, `delete-view`.

Tests: 161 pass (`tests/test_views.py`: save/list/apply/delete round trip,
survives close and reopen, name checks, one default per table, rename,
following a field rename, going with a field or table drop; plus bridge
and MCP tests, including the default view applying on reopen).

To try Tim's case: Show rows where Moved is not Yes → Apply → Views… →
Save view… → "Still here" → Save. Close the database, open it again, Views…
→ Still here. Delete it from the same menu; the rows stay.

Not done: applying a view from the report dialog by name (the report still
uses "the filter on now", which is the view's rule once picked); column sort.

## 2026-09-22 (later) — Add fields, and "Show rows where…"

Tim's next asks: add a field to a table (a "Moved" yes/no), and hide rows on
the main view by a field. Both landed, and reports can use the same rule.

**Add field.** More… → Fields → **Add field…**: Label, Name inside (made
from the label as you type, editable), Type (the same five as the import
wizard). Rows already there get nothing in it. Storage `add_field` is
`ALTER TABLE … ADD COLUMN` plus the field meta; the form shows the new
field at the end. Bad or duplicate names are refused in words. MCP
`add_field` (label, optional name, type).

**Show rows where… (the main view).** A bar above the grid and the form:
*Show rows where* [Field] [is / is not / is empty / is not empty / contains]
[value] **Apply** **Clear**. The rule is positive on purpose: to hide people
who moved, say "Moved is not Yes" (blank counts as not Yes). Yes/no fields
take yes/no/true/false/1/0. The grid and the form both use the filtered set,
so Previous / Next only walk matching rows; Delete row and Add row stay on
the filtered view (a new row that does not match is saved and drops out of
sight). The footer says "Showing 20 of 32 rows where Moved is not Yes".
Clear is one click. The rule is remembered per table while the database is
open, and dropped quietly if its field is renamed or deleted. "contains" is
for words fields only.

One helper, `jubako/filters.py`, makes the SQL for everyone: the grid,
the form, reports, the CLI (`rows --filter FIELD OP [VALUE]`) and MCP
(`list_rows` takes `filter: {field, op, value}`). There is no free-form SQL:
the field must be one of the table's, the match is one of five, and the value
is bound as a parameter after being read the way the field's type wants.

**Reports.** The report designer shows "Only rows where Moved is not Yes"
(ticked) when the table has a filter on; untick it to print every row. The
spec stores the filter, kept reports keep it, the PDF says "Only rows where
…" under the title, and `create_report` / `export_report` in MCP take
`filter` too. To print only some rows, filter the table first; the dialog
says so when there is no filter.

Tim's example, tried offscreen and in tests: import pets, Add field "Moved"
(yes/no), mark two rows Yes, "Show rows where Moved is not Yes" → 2 of 4,
the form walks those two, Print report shows 2 rows with the rule under the
title.

Tests: 152 pass (`tests/test_filters.py` is new: add field, every match on
a yes/no field and on words/numbers/dates, blanks, refusals in words,
injection-shaped values bound harmlessly, filter words, filtered reports;
plus bridge and MCP tests).

Not done, on purpose: AND/OR combinations, "any field", saved named
queries. The filter is not written into the database file (it lives in the
window); a kept report is the way to keep a rule.

## 2026-09-22 — Import every sheet, delete things, rename fields

Tim's asks after the Tyler import, all landed:

**Import every sheet as its own table (off by default).** The import wizard
shows a checkbox, "Import every sheet as its own table", only when the
workbook has more than one sheet. Unchecked (the default) nothing changes:
one sheet, one table, editable types. Checked, the sheet picker and the
column list give way to a list of "sheet → table" names; each sheet uses
guessed types (the wizard says so); the button reads "Import 3 sheets". If
some of those tables already exist, **one** confirm names them all
("Replace 2 tables? These are already in this database: a, b") rather than
one dialog per sheet. The work runs on the worker thread and one
`importFinished` carries `{tables, errors}`; a sheet that cannot be read
(empty, no column names) is skipped and named in a toast, the rest still go
in. Core: `importer.import_workbook`; CLI `import --all-sheets`; MCP
`import_spreadsheet` with `all_sheets: true` (or `sheet: "*"`). Verified on
Tim's Tyler workbook through the app's wizard path: three tables
(`consolidated_list` 15 fields / 25 rows, `clean_list_for_print` 9 / 32,
`no_longer_in_the_area` 15 / 8) in 0.05 s.

**Delete.** Rows: unchanged (Delete row above the grid, Delete this row in
the form, confirm each). New, each with its own confirm in plain words:

- *Fields*: More… → "Fields: rename or delete…" lists every field (label,
  name inside, type) with Rename… and Delete…. Delete warns that everything
  in that column is gone. A table keeps at least one field (the storage
  refuses to drop the last one; delete the table instead). Storage
  `drop_field` is `ALTER TABLE … DROP COLUMN` on all three engines (SQLite
  ≥ 3.35; this machine has 3.53).
- *Tables*: More… → "Delete this table…" names the table and its row count;
  the table's kept form and reports go with it (`schema.drop_table`).
- *Whole database*: More… → "Delete this whole database…" shows the file
  path and "cannot be undone"; the connection closes, the file and any
  `-wal` / `-shm` / `-journal` sidecars are removed, the recent list forgets
  it, and the window returns Home. Only for a local `.jubadb`; for a
  PostgreSQL or MySQL database the menu item is disabled and the bridge
  and MCP refuse with "a server database is left alone". On Home, each
  recent entry has a "…" menu with "Remove from this list" and "Delete the
  file…" (the latter confirms; disabled for server entries).

**Rename fields.** Rename… opens a dialog with *Label* (what people see)
and *Name inside the database*, pre-filled; Save changes either or both.
Storage `rename_field` is `ALTER TABLE … RENAME COLUMN` plus the field
meta; `relabel_field` touches only the meta. Names follow the usual rules
(letters, numbers, underscores; not `id`; no clash). Kept forms and reports
follow the new name (`schema._retarget`); a dropped field is taken out of
them, and a report left with no columns is forgotten rather than left
broken.

**MCP** (23 tools now): `rename_field` (name and/or label), `delete_field`,
`delete_table`, `delete_database` (sqlite path only, needs `confirm: true`),
and `all_sheets` on `import_spreadsheet`.

**Also**: the importer now parses a workbook once and keeps the last one
(keyed on path, mtime and size), so planning and importing every sheet no
longer re-reads the file per sheet. The worker-thread tests now wait on the
`importFinished` signal with an event loop instead of polling (see the note
below on why polling starves the worker).

Tests: 143 pass (`tests/test_schema.py` is new: rename, relabel, refusals,
drop field and its data, last-field guard, forms/reports following renames
and drops, drop table, delete file, import every sheet incl. an empty sheet
and a CSV; plus bridge and MCP tests for each).

To try it: open a database, Import spreadsheet, pick the Tyler workbook,
tick "Import every sheet as its own table", Import. Then More… for Fields
and the two deletes; "…" on a Home entry for the file.

## Fix 2026-09-22 — Excel import of a titled sheet collapsed to one column

Tim imported `Tyler_Community_Consolidated_List_1.1.xlsx` and got a single
field. The reader took the first non-blank row as the headers; on a normal
titled sheet that row is the title alone in A1, so every later row was cut
to one column. Now `read_xlsx`:

1. **Prefers the sheet's Excel Table** when it has one (the largest, if
   several): headers and data come from the Table's range, and cells outside
   it (footers, totals) are ignored. This needs the workbook opened
   normally rather than read-only, because read-only sheets do not expose
   their Tables.
2. **Otherwise finds the header row by looking**: among the first 30 rows,
   the first row at least half as wide as the widest and with two or more
   filled cells. A lone title never qualifies; a header row with a blank
   cell still does. The table is as wide as the last column with a heading
   or with data below it, and a column with data but no heading is called
   "Column 3" rather than dropped. A genuinely one-column sheet still works.

Verified on Tim's file: all three sheets — "Consolidated List" (Excel Table
`ConsolidatedMembers` A5:O30, 15 fields, 25 rows), "Clean_List_For_Print"
(Table, 9 fields, 32 rows) and "No Longer in the Area" (no Table; title,
subtitle, two blank rows, headers on row 5; 15 fields, 8 rows) — plan and
import with the real headers (IDN, First Name, Middle / Nickname, Last Name,
Mail Status, Address Line 1, City, State, ZIP, Home Phone, Work Phone, Cell
Phone, Email, Record Type, Notes), through the CLI and through the app's
wizard path (bridge `planImport` / `importPlanned` on the worker thread).
Four new tests build workbooks of these shapes; 127 tests pass.

A note for whoever writes the next worker-thread test: waiting on the import
with a tight `QTest.qWait` loop makes the worker about a hundred times
slower (the loop keeps taking the GIL back from the CPU-bound openpyxl
parse). With the real event loop running (`app.exec()`) the same import of
Tim's sheet finishes in 0.18 s. Poll with a longer wait, or quit the event
loop from the `importFinished` signal, as the verification here did.

Worth knowing: on the sheet without dashes in its ZIP codes the type guesser
calls ZIP a whole number, which the wizard lets you change to words before
importing. That is the guesser's normal behaviour, not part of this bug.

Phase B is complete on this machine, in the order Tim asked for: B0 (live
theme follow) first, then the form view and grid editing, then Excel import
and export, fitted PDF reports with preview and system print, the import
wizard, and a worker thread for imports. The one open item carried from Phase
A remains: no live PostgreSQL or MySQL server has been connected to from
here (see [Not yet verified](#not-yet-verified)). Phase C (packaging) is
mostly not started.

## What changed in Phase B

### B0 — the window follows `omarchy theme set` (verified live)

`omarchy theme set` does `rm -rf current/theme` and then `mv theme.next
current/theme`, so a watch on `colors.toml` went stale the moment the theme
changed. The app now watches `~/.local/state/omarchy/current/` itself and
`theme.name` (which are rewritten in place), re-arms the inner watches after
every change, waits for the burst of events to settle, reads `colors.toml`
once the new directory is there, rebuilds the palette and emits
`Theme.changed`. The QML binds to `Theme.*` (`Theme.window`, `Theme.base`,
`Theme.alternateBase`, `Theme.accent`, …), never to `palette.*`.

Verified with the window open: switched from the guild theme to Gruvbox and
back; the window recoloured each time (screenshots taken at each step). A
unit test performs the same rm-rf-then-rename twice.

### B1 — form view and grid editing

- **Form**: one record at a time. Previous / Next, "Row 2 of 4", New row,
  Save (or "Add this row"), Undo changes, Delete this row. Yes/no fields are a
  checkbox; other fields are a box to type in with a hint of what fits.
- **Grid**: tap a row to pick it, double-tap a cell (or Enter / F2) to type in
  it. Add row and Delete row buttons above the grid. Delete asks first.
- Values that do not fit come back in words: "age needs a whole number.
  “three” does not fit."
- The form honours a form kept in the database (`create_form` in MCP): field
  order and labels.

### B2 — Excel, reports, printing, import wizard, worker thread

- **Excel (.xlsx) import and export** with `openpyxl` (optional extra
  `xlsx`). Import reads one sheet per call (the wizard and MCP let you pick),
  uses the values Excel last saved for formulas, and never runs anything.
  Export writes real Excel types (numbers, dates, booleans), bold headings,
  frozen header row. Old `.xls` is refused with advice.
- **Reports**: `jubako/reports.py` holds the spec (table, columns, title,
  page size Letter/A4/Legal, orientation, margins, fit-to-width, text size,
  row numbers), the row fetch and the column-fitting arithmetic; forms and
  reports are kept inside the database in Jubako's own info table.
  `jubako/printing.py` lays out and paints pages with Qt: one
  `ReportDocument` writes the PDF, prints to a `QPrinter`, and renders the
  preview image, so what you preview is what you print. Fit-to-width shrinks
  columns proportionally (never below their longest word) and wraps cells;
  rows never clip; pages number "Page n of N".
- **In the app**: "Print report" opens the designer: title, column
  checkboxes, page, orientation, fit, margins, text size, keep-by-name, list
  of kept reports; a live preview that relays out 250 ms after each change,
  with page arrows; "Print…" opens the system print dialog (`QPrintDialog`),
  "Save PDF…" a save dialog. "Export…" writes the current table as CSV or
  Excel.
- **Import wizard**: every import now goes through one screen showing the
  file, the sheet (when there is more than one), the table name, and each
  column's label, guessed type (editable) and a few sample values. Replacing
  a table still asks first.
- **Worker thread**: for a file database the import runs on a `QThread` with
  its own SQLite connection; the wizard shows a spinner and cannot be closed
  until it is done. Server databases import in place (their connection is
  not re-openable without the password).
- **MCP**: new tools `update_row`, `delete_row`, `create_form`, `get_form`,
  `create_report`, `list_reports`, `delete_report`, `export_report`;
  `import_spreadsheet` and `plan_import` take `sheet`; `export_table` takes
  `format` csv | xlsx | pdf. 19 tools in all.
- **CLI**: `jubako report <db> <table> <out.pdf> [--title --columns --page
  --landscape --no-fit]`; `export --format csv|xlsx|pdf`; `import --sheet`.
- **Host**: `QApplication` instead of `QGuiApplication`, only because the
  system print dialog is a widget. The UI is still all QML.

## Verified

- `python -m pytest` — **162 passed** (161 after saved views plus the Add
  field window test; the 161 were 152 after filters and add-field plus
  the saved-view tests; the 152 were 143 after import-all/delete/rename
  plus the filter and add-field tests; the 143 were 127 after the Excel
  header fix plus schema, import-all, bridge and MCP tests; the 127 were 123 after Phase B
  plus the four Excel header tests; the 123 were 101 after A2, plus theme swap, editing,
  import worker, export, report bridge, xlsx round trip, sheet choice, saved
  formula values, column fitting, pagination, PDF bytes, printer path,
  preview orientation, forms and reports kept in the database, and the new
  MCP tools end to end).
- Live theme follow under Hyprland: theme switched twice with the window
  open; the window recoloured both times.
- Launched live after every milestone; last launch under the Lumon theme
  shows Grid / Form, Add row / Delete row, Export…, Print report.
- Offscreen renders inspected: grid row selection, in-place cell editor, the
  form ("Row 2 of 4"), the report designer with its preview, the import
  wizard on a two-sheet workbook (imported the People sheet with the right
  types), a landscape one-page PDF and a seven-page wrapping report whose
  PDF pages (via `pdftoppm`) match the preview image.
- MCP: `jubako-mcp --tools` lists 19 tools; the MCP test drives
  update/delete row, create/get form, create/list/export/delete report
  through the real handlers.
- CLI: `jubako report … --landscape` wrote a one-page PDF.

## Not yet verified

- **Live PostgreSQL and MySQL/MariaDB connect.** Unchanged: drivers
  installed, code paths unit-tested offline, no server reachable from this
  machine (no local server binaries; Docker socket needs root). Optional per
  Tim; `scripts/smoke_remote.py` is ready.
- **Pressing Print in the system dialog.** The dialog cannot be driven from
  here. The path it feeds (`ReportDocument.print_to(QPrinter)`) is tested by
  printing to a PDF-format `QPrinter`, and the dialog constructs.
- **Forms and reports on server backends.** They are kept in Jubako's
  own info table through the shared storage interface, so they should work
  on all three engines, but have only run on SQLite.

## Phase B success criteria (from the brief)

| Criterion | State |
|---|---|
| B0: window tracks `omarchy theme set` while open | done, verified live |
| Form view: one record, next/prev, save | done |
| Grid add/edit/delete | done |
| xlsx import and export | done |
| Report preview + PDF + system print with fit-to-width | done (print dialog opens; printing to a PDF printer tested) |
| Import wizard: editable mapping and type guesses | done (types and table name editable; column renaming is not) |
| Polish empty states | done in A2; wizard and form add their own hints |
| Worker thread for imports | done for SQLite; in place for servers |
| MCP `update_row` / `delete_row` / `create_form` / `create_report` / `export_report` | done |
| STATUS.md updated | done |

## Engine-specific limits

- **SQLite** keeps dates as ISO text and yes/no as 0/1. The library turns them
  back into real dates and yes/no on the way out, so all three engines look the
  same to the app. PostgreSQL and MySQL use their own `DATE` and boolean types.
- **Row identity.** Every table Jubako makes gets an automatic `id`. A
  table made outside Jubako without an `id` column can be listed and read
  (its row number shows blank), but `update_row` / `delete_row` refuse it
  and the grid will not edit it; a banner offers **Add a row number**
  (`schema.add_row_number`). SQLite rebuilds the table to add it (all rows
  and values kept, original column constraints are not); PostgreSQL and
  MySQL add the column in place.
- **No repeats.** A unique index named `jubako_u_<hash>`. Blanks may repeat
  on every engine. MySQL indexes the first 191 characters of a words field,
  and its default collation treats "Ann" and "ann" as the same value;
  SQLite and PostgreSQL do not.
- **Where a database lives.** SQLite is a file the user picks. For PostgreSQL
  and MySQL, the *server* and the *database* must already exist. The app never
  passes `overwrite` for a server.
- **Imports on server backends** run on the GUI thread (see worker thread
  above) and have only been exercised against SQLite.
- **Re-opening a recent server database** needs the password typed again
  (by design).
- **Report size.** A report reads at most 20,000 rows; column widths are
  measured on the first 2,000. The grid shows the first 500 rows of a table.

## Decisions worth knowing

- **Pixel-size fonts in reports.** The painter is scaled so one unit is one
  point on every target (PDF at 300 dpi, printer, preview image). Point-size
  fonts already follow the device DPI and came out double-scaled; pixel-size
  fonts do not, so measuring and painting agree everywhere.
- **Reports live in the core, Qt is imported lazily.** The core still installs
  with no third-party packages; `printing.py` imports PySide6 only when a PDF
  is made, and starts an offscreen `QGuiApplication` if none exists (that is
  how the MCP server and CLI make PDFs).
- **Forms and reports are stored in the database file**, under `form:<table>`
  and `report:<name>` keys in `jubako_info`, so they travel with the `.jubadb`.
- **The wizard is the only import path in the window.** Dropping a file,
  the Import button and the first-run path all open it, so the type guesses
  are always shown before anything is written.
- **PySide6 host; Fusion style + palette; work on the GUI thread except
  imports; Python not Rust; MCP with no SDK; names refused not escaped** —
  unchanged from earlier phases.

## Next — Phase C (mostly not started, waiting on Tim)

- `scripts/install-launcher.sh` exists (done early in A2). Still to do: an
  optional PKGBUILD draft for `omarchy-pkgs`. Nothing to be published without
  Tim.

## Loose ends worth a later pass

- Column renaming in the import wizard itself (rename after import via
  More… → Fields instead).
- Sort in the grid (filter is done; sorting by a column is not).
- Reports: choose sort order; group headings; a header/footer of your own.
- Open a database on the worker thread too (only imports are off-thread today).
- A drag-over highlight while a file is being dropped on the window.
- Live PostgreSQL / MySQL smoke, then confirm forms, reports and imports there.
