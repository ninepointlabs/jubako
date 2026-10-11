"""Show rows where <field> <is / is more than / contains / ...> <value>, and in what order.

One small, safe filter shared by the grid, the form, reports and the MCP
server. There is no free-form SQL: the field must be one of the table's, the
match is one of a short list, and the value is bound as a parameter after
being read the way the field's type wants (so a yes/no field accepts yes, no,
true, false, 1 or 0).

A filter is one rule, {field, op, value}, or several rules matched all
("and") or any ("or"): {match: "all" | "any", rules: [rule, ...]}. A list of
one rule is kept as the plain rule, so filters saved before rules could be
combined read the same.

A sort is a short list of {field, descending}. Blanks always go last, on
every engine, and the row number breaks ties so the order never wobbles.
"""

from __future__ import annotations

from typing import Any

from .errors import BadName, JubakoError
from .fields import BOOLEAN, DATE, INTEGER, REAL, TEXT, Field, coerce

OPS = (
    "is", "is_not", "empty", "not_empty", "contains", "starts_with",
    "more_than", "less_than", "at_least", "at_most",
)

#: The words people see for each match.
OP_WORDS = {
    "is": "is",
    "is_not": "is not",
    "empty": "is empty",
    "not_empty": "is not empty",
    "contains": "contains",
    "starts_with": "starts with",
    "more_than": "is more than",
    "less_than": "is less than",
    "at_least": "is at least",
    "at_most": "is at most",
}

#: For a date the same comparisons read as before and after.
DATE_OP_WORDS = {
    "more_than": "is after",
    "less_than": "is before",
    "at_least": "is on or after",
    "at_most": "is on or before",
}

NEEDS_VALUE = {"is", "is_not", "contains", "starts_with", "more_than", "less_than", "at_least", "at_most"}
TEXT_OPS = {"contains", "starts_with"}
ORDER_OPS = {"more_than", "less_than", "at_least", "at_most"}
ORDERED_TYPES = {INTEGER, REAL, DATE}
MATCHES = ("all", "any")
MAX_RULES = 10
MAX_SORT = 3

_ALIASES = {
    "is_not_empty": "not_empty",
    "is_empty": "empty",
    "is_more_than": "more_than",
    "is_less_than": "less_than",
    "is_at_least": "at_least",
    "is_at_most": "at_most",
    "after": "more_than",
    "is_after": "more_than",
    "before": "less_than",
    "is_before": "less_than",
    "on_or_after": "at_least",
    "is_on_or_after": "at_least",
    "on_or_before": "at_most",
    "is_on_or_before": "at_most",
    ">": "more_than",
    "<": "less_than",
    ">=": "at_least",
    "<=": "at_most",
    "=": "is",
    "!=": "is_not",
}

_SQL_COMPARE = {"more_than": ">", "less_than": "<", "at_least": ">=", "at_most": "<="}


def op_words(op: str, field_type: str | None = None) -> str:
    """How a match reads for a field of this type: "is more than", or "is after" for a date."""
    if field_type == DATE and op in DATE_OP_WORDS:
        return DATE_OP_WORDS[op]
    return OP_WORDS.get(op, op)


def ops_for(field_type: str) -> list[str]:
    """The matches that make sense for a field of this type, in the order people see them."""
    out = ["is", "is_not", "empty", "not_empty"]
    if field_type == TEXT:
        out += ["contains", "starts_with"]
    if field_type in ORDERED_TYPES:
        out += ["more_than", "less_than", "at_least", "at_most"]
    return out


# -------------------------------------------------------------------------
# Filters
# -------------------------------------------------------------------------

def normalise_filter(fields: list[Field], raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Check a filter against a table's fields. Returns None for "no filter"."""
    if not raw:
        return None
    if "rules" not in raw:
        return _normalise_rule(fields, raw)
    match = str(raw.get("match") or "all").strip().lower()
    if match in ("and", "every"):
        match = "all"
    if match in ("or", "either"):
        match = "any"
    if match not in MATCHES:
        raise JubakoError(f"Unknown way to combine rules {raw.get('match')!r}. Use all or any.")
    rules = [rule for rule in (raw.get("rules") or []) if rule]
    if len(rules) > MAX_RULES:
        raise JubakoError(f"A filter can have at most {MAX_RULES} rules.")
    checked = [_normalise_rule(fields, rule) for rule in rules]
    if not checked:
        return None
    if len(checked) == 1:
        return checked[0]
    return {"match": match, "rules": checked}


def _normalise_rule(fields: list[Field], raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise JubakoError("A rule is a field, a match and (for most matches) a value.")
    field_name = str(raw.get("field") or "").strip()
    op = str(raw.get("op") or "is").strip().lower().replace(" ", "_")
    op = _ALIASES.get(op, op)
    known = {f.name: f for f in fields}
    if field_name not in known:
        raise BadName(f"This table has no field called {field_name!r}.")
    if op not in OPS:
        raise JubakoError(f"Unknown match {raw.get('op')!r}. Use: {', '.join(OPS)}.")
    field = known[field_name]
    value: Any = raw.get("value")
    if op in NEEDS_VALUE:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise JubakoError(f"Say what {field.title} {op_words(op, field.type)}.")
        if op in TEXT_OPS:
            if field.type != TEXT:
                raise JubakoError(f"“{OP_WORDS[op]}” only works on a words field. Use “is” instead.")
            value = str(value)
        else:
            if op in ORDER_OPS and field.type not in ORDERED_TYPES:
                raise JubakoError(
                    f"“{OP_WORDS[op]}” only works on a number or a date. {field.title} holds "
                    f"{_kind_word(field.type)}."
                )
            try:
                value = coerce(value, field.type)
            except (ValueError, TypeError):
                raise JubakoError(
                    f"“{value}” is not a {_kind_word(field.type)}, which is what {field.title} holds."
                ) from None
    else:
        value = None
    return {"field": field_name, "op": op, "value": value}


def filter_rules(filter_spec: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The rules of a filter as a list (one rule, several, or none)."""
    if not filter_spec:
        return []
    if "rules" in filter_spec:
        return list(filter_spec["rules"])
    return [filter_spec]


def filter_match(filter_spec: dict[str, Any] | None) -> str:
    """"all" or "any": how the rules combine. One rule reads as "all"."""
    if filter_spec and "rules" in filter_spec:
        return filter_spec.get("match", "all")
    return "all"


def filter_fields(filter_spec: dict[str, Any] | None) -> set[str]:
    """Every field a filter looks at."""
    return {rule["field"] for rule in filter_rules(filter_spec)}


def rename_in_filter(filter_spec: dict[str, Any] | None, old: str, new: str) -> dict[str, Any] | None:
    """The same filter, with a renamed field's new name."""
    if not filter_spec:
        return filter_spec
    rules = [{**rule, "field": new} if rule["field"] == old else rule for rule in filter_rules(filter_spec)]
    if "rules" in filter_spec:
        return {**filter_spec, "rules": rules}
    return rules[0]


def where_clause(storage: Any, filter_spec: dict[str, Any] | None, *, first_index: int = 0) -> tuple[str, list[Any]]:
    """The SQL after WHERE (empty for no filter) and its parameters."""
    rules = filter_rules(filter_spec)
    if not rules:
        return "", []
    parts: list[str] = []
    params: list[Any] = []
    for rule in rules:
        clause, more = _rule_clause(storage, rule, first_index + len(params))
        parts.append(clause)
        params.extend(more)
    if len(parts) == 1:
        return parts[0], params
    joiner = " OR " if filter_match(filter_spec) == "any" else " AND "
    return "(" + joiner.join(f"({part})" for part in parts) + ")", params


def _rule_clause(storage: Any, rule: dict[str, Any], index: int) -> tuple[str, list[Any]]:
    column = storage.quote(rule["field"])
    op = rule["op"]
    value = rule["value"]
    mark = storage.placeholder(index)
    if op == "is":
        return f"{column} = {mark}", [_param(value, storage)]
    if op == "is_not":
        return f"({column} IS NULL OR {column} <> {mark})", [_param(value, storage)]
    if op == "empty":
        return f"({column} IS NULL OR CAST({column} AS CHAR(1)) = '')", []
    if op == "not_empty":
        return f"({column} IS NOT NULL AND CAST({column} AS CHAR(1)) <> '')", []
    if op in TEXT_OPS:
        # "!" escapes the wildcards: a backslash would mean something else inside a MySQL string.
        escaped = str(value).replace("!", "!!").replace("%", "!%").replace("_", "!_")
        pattern = f"{escaped}%" if op == "starts_with" else f"%{escaped}%"
        return f"LOWER({column}) LIKE LOWER({mark}) ESCAPE '!'", [pattern]
    if op in _SQL_COMPARE:
        return f"{column} {_SQL_COMPARE[op]} {mark}", [_param(value, storage)]
    raise JubakoError(f"Unknown match {op!r}.")


def filter_words(fields: list[Field], filter_spec: dict[str, Any] | None) -> str:
    """The rule in plain words: "Moved is not Yes", or "Age is more than 3 and Moved is Yes"."""
    rules = filter_rules(filter_spec)
    if not rules:
        return ""
    joiner = " or " if filter_match(filter_spec) == "any" else " and "
    return joiner.join(_rule_words(fields, rule) for rule in rules)


def _rule_words(fields: list[Field], rule: dict[str, Any]) -> str:
    known = {f.name: f for f in fields}
    field = known.get(rule["field"])
    label = field.title if field else rule["field"]
    kind = field.type if field else None
    op = rule["op"]
    if op in NEEDS_VALUE:
        value = rule["value"]
        if kind == BOOLEAN:
            value = "Yes" if value else "No"
        elif isinstance(value, float) and value.is_integer():
            value = int(value)  # "more than 3000", not "3000.0"
        return f"{label} {op_words(op, kind)} {value}"
    return f"{label} {op_words(op, kind)}"


# -------------------------------------------------------------------------
# Sorting
# -------------------------------------------------------------------------

def normalise_sort(fields: list[Field], raw: Any) -> list[dict[str, Any]]:
    """Check a sort against a table's fields: a list of {field, descending}, at most three.

    Accepts one {field, descending} or a list of them; "id" (the row number)
    is allowed too. Empty means "in the order the rows were added".
    """
    if not raw:
        return []
    items = raw if isinstance(raw, list) else [raw]
    if len(items) > MAX_SORT:
        raise JubakoError(f"Sort by at most {MAX_SORT} fields.")
    known = {f.name for f in fields} | {"id"}
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            item = {"field": item}
        name = str(item.get("field") or "").strip()
        if name not in known:
            raise BadName(f"This table has no field called {name!r}.")
        if any(existing["field"] == name for existing in out):
            continue
        out.append({"field": name, "descending": bool(item.get("descending", False))})
    return out


def order_clause(storage: Any, sort: list[dict[str, Any]], *, row_id: bool = True) -> str:
    """The SQL after ORDER BY: blanks last for every field, then the row number (when there is one)."""
    parts = []
    for item in sort:
        column = storage.quote(item["field"])
        direction = "DESC" if item["descending"] else "ASC"
        if item["field"] != "id":
            parts.append(f"({column} IS NULL) ASC")
        parts.append(f"{column} {direction}")
    if row_id and not any(item["field"] == "id" for item in sort):
        parts.append(f"{storage.quote('id')} ASC")
    return ", ".join(parts)


def sort_words(fields: list[Field], sort: list[dict[str, Any]] | None) -> str:
    """The sort in plain words: "Age, highest first, then Name, A to Z"."""
    if not sort:
        return ""
    known = {f.name: f for f in fields}
    parts = []
    for item in sort:
        field = known.get(item["field"])
        label = field.title if field else ("Row number" if item["field"] == "id" else item["field"])
        kind = field.type if field else INTEGER
        parts.append(f"{label}, {direction_words(kind, item['descending'])}")
    return ", then ".join(parts)


def direction_words(kind: str | None, descending: bool) -> str:
    """"A to Z", "lowest first", "oldest first", and their opposites."""
    pairs = {
        TEXT: ("A to Z", "Z to A"),
        DATE: ("oldest first", "newest first"),
        BOOLEAN: ("No first", "Yes first"),
    }
    up, down = pairs.get(kind or "", ("lowest first", "highest first"))
    return down if descending else up


def _param(value: Any, storage: Any) -> Any:
    if isinstance(value, bool) and getattr(storage, "backend", "") == "sqlite":
        return int(value)  # SQLite keeps 0/1; PostgreSQL wants a real boolean (it has no boolean = smallint)
    return value


def _kind_word(kind: str) -> str:
    return {"integer": "whole number", "real": "number", DATE: "date like 2024-01-31",
            BOOLEAN: "yes or no"}.get(kind, "words")
