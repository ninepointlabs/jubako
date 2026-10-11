# Jubako — todo: the Access features worth having

Items 1–7 from the Access comparison (2026-10-10), easiest first. Macros and
VBA modules are left out on purpose: the CLI and the MCP server do that job.
Relationships (lookup fields) come after this list: see 8.

Each item is done when it works in the core library, the CLI, the MCP server
and the window, with tests. Work order: 7a → 6 → 4 → 2 → 3 → 5 → 7b.

## 1. Tables — done

- [x] Make, import, browse, edit; add, rename and delete fields.

## 2. Primary keys

- [x] "No repeats" on a field (a unique field, like an email or a SKU). Kept in
      the field spec, enforced by a unique index on all three engines. Turning
      it on is refused while repeats exist, and says which values repeat.
- [x] A table made outside Jubako with no `id`: offer "Add a row number" so the
      grid and form can edit it.

## 3. Backstage (the File menu)

- [x] One "Database" menu in the header: New, Open, Recent, Save a copy…,
      Rename database…, Close, Delete database.
- [x] Save a copy of a file database (SQLite backup, safe while open).
- [x] Rename the database's title.

## 4. Templates

- [x] A template format: tables, fields, a few sample rows, views, reports.
- [x] Starter templates: Contacts, Inventory, Projects & tasks,
      Customer service, Home collection.
- [x] `apply_template` in the core; `jubako new --template`; MCP `create_database` + `list_templates`.
- [x] "Start from a template" on Home and in the New database dialog.

## 5. Forms

- [x] Form designer: field order, hide a field, relabel, form title (the core
      `save_form` already stores order and labels; there is no window for it).
- [x] Hidden fields stay out of the form but keep their data.
- [x] Form buttons: Duplicate this record.

## 6. Reports

- [x] Sort order (one or more fields, up or down).
- [x] Group by a field, with a heading per group.
- [x] Totals: row count per group and overall; sum and average for numbers.
- [x] Your own header and footer line.
- [x] Use a saved view by name.

## 7. Queries

### 7a. One table, no SQL

- [x] Sort the grid by tapping a column heading (up, down, off). Blanks last.
- [x] Comparisons: more than / less than / at least / at most for numbers;
      before / after / on or before / on or after for dates; starts with.
- [x] Several rules, matched all ("and") or any ("or").
- [x] Saved views keep their sort as well as their rules.

### 7b. Doing things with the rows you found

- [x] Change a field in every matching row ("set Moved to Yes"), with a confirm.
- [x] Delete every matching row, with a confirm that says how many.
- [x] Summary of the matching rows: count, and sum / average of a number field.

## 8. Relationships: lookup fields

A lookup field points at a row of another table, like an order's Customer
pointing at a row of `customers`. It keeps that row's number and shows one of
its fields (the customer's Name), so renaming "Ann Lee" in `customers` shows
everywhere at once.

Decisions (2026-10-10):
- **Stored as the other row's `id`** (an integer column), shown as the chosen
  field's text. Rows from `list_rows` carry the text people see, with the ids
  alongside, so reports, exports and the CLI show names without knowing.
- **Typing a name finds the row**: a write may give the text (matched without
  minding case) or the row number. No match, or two rows with that text, is
  refused in words.
- **Filters and sorts use the text** ("Customer contains lee", A to Z by name).
- **Deleting a row that others point at is refused**, saying how many rows
  point at it. Deleting the other table, or the field it shows, is refused
  while a lookup uses it. Renaming that field follows.
- No database-level foreign keys: Jubako checks, the same on all three engines.
- **The shown field must be a words field**, and a lookup cannot be no-repeats (yet).

- [x] Core: the `lookup` type (`target`, `show`), add a lookup field, writes
      resolve and check, `list_rows` shows the text, filters and sorts on it.
- [x] Protection: deleting pointed-at rows, dropping the target table or the
      shown field; renames follow.
- [x] Turn an existing words field into a lookup ("Customer" names in
      `orders` → rows of `customers`), saying which values match nothing.
- [x] Reports, exports and summaries show the text.
- [x] CLI and MCP.
- [x] Window: add a lookup field; the form picks from a list; the grid takes
      a typed name; the filter bar.
