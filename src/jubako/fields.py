"""Field types, in plain words.

Jubako keeps five kinds of field. Every backend maps them onto its own
column types, so a table made on SQLite looks the same on PostgreSQL.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any

TEXT = "text"
INTEGER = "integer"
REAL = "real"
DATE = "date"
BOOLEAN = "boolean"

FIELD_TYPES = (TEXT, INTEGER, REAL, DATE, BOOLEAN)

#: What people see in the app when they pick a type.
FIELD_TYPE_LABELS = {
    TEXT: "Words",
    INTEGER: "Whole number",
    REAL: "Number with decimals",
    DATE: "Date",
    BOOLEAN: "Yes / No",
}

TRUE_WORDS = {"true", "yes", "y", "t", "1", "on"}
FALSE_WORDS = {"false", "no", "n", "f", "0", "off"}

_NAME_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Reserved prefix for Jubako's own bookkeeping tables.
INTERNAL_PREFIX = "jubako_"
#: The prefix databases made before the rename to Jubako still carry.
LEGACY_INTERNAL_PREFIX = "omadb_"


#: Field types that can be marked "no repeats" (a yes/no field only has two values).
UNIQUE_TYPES = (TEXT, INTEGER, REAL, DATE)


@dataclass(frozen=True)
class Field:
    """One column: the safe name, the label people read, the type, and whether values may repeat."""

    name: str
    type: str = TEXT
    label: str | None = None
    unique: bool = False

    def __post_init__(self) -> None:
        if self.type not in FIELD_TYPES:
            raise ValueError(f"Unknown field type: {self.type!r}")

    @property
    def title(self) -> str:
        return self.label or self.name.replace("_", " ").strip().title()


def field_dict(field: Field) -> dict:
    """A field as plain data: name, type, label, and "unique": True only for a no-repeats field."""
    out = {"name": field.name, "type": field.type, "label": field.title}
    if field.unique:
        out["unique"] = True
    return out


def is_safe_name(name: str) -> bool:
    """True when a name can go straight into SQL without quoting tricks."""
    return bool(_NAME_OK.match(name)) and len(name) <= 63


def slugify_name(raw: str, *, fallback: str = "field") -> str:
    """Turn a spreadsheet heading into a safe field name.

    "First Name" -> "first_name"; "2024 total ($)" -> "c_2024_total".
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (raw or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned[:63]


def unique_names(raw_names: list[str], *, fallback: str = "field") -> list[str]:
    """Slugify headings and make sure no two end up the same."""
    out: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_names):
        base = slugify_name(raw, fallback=f"{fallback}_{index + 1}")
        name = base
        counter = 2
        while name in seen:
            name = f"{base}_{counter}"[:63]
            counter += 1
        seen.add(name)
        out.append(name)
    return out


def parse_boolean(value: str) -> bool | None:
    text = value.strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    return None


def parse_date(value: str) -> _dt.date | None:
    """Accept the date shapes people actually type. No guessing beyond these."""
    text = value.strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%b %d, %Y"):
        try:
            return _dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def coerce(value: Any, field_type: str) -> Any:
    """Turn a cell of text into the value a field of this type wants.

    Empty text becomes None (blank), never 0 or False.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
    else:
        text = value

    if field_type == TEXT:
        return str(text)
    if field_type == INTEGER:
        if isinstance(text, bool):
            return int(text)
        if isinstance(text, int):
            return text
        if isinstance(text, float) and float(text).is_integer():
            return int(text)
        return int(str(text).replace(",", "").strip())
    if field_type == REAL:
        if isinstance(text, (int, float)) and not isinstance(text, bool):
            return float(text)
        return float(str(text).replace(",", "").strip())
    if field_type == BOOLEAN:
        if isinstance(text, bool):
            return text
        parsed = parse_boolean(str(text))
        if parsed is None:
            raise ValueError(f"Not a yes/no value: {value!r}")
        return parsed
    if field_type == DATE:
        if isinstance(text, _dt.datetime):
            return text.date()
        if isinstance(text, _dt.date):
            return text
        parsed = parse_date(str(text))
        if parsed is None:
            raise ValueError(f"Not a date: {value!r}")
        return parsed
    raise ValueError(f"Unknown field type: {field_type!r}")
