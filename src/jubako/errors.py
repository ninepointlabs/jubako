"""Errors that Jubako raises. Messages are meant to be shown to people."""


class JubakoError(Exception):
    """Base class. Anything we raise on purpose is one of these."""


class PathNotAllowed(JubakoError):
    """A file path pointed outside the folders the user approved."""


class BackendNotAvailable(JubakoError):
    """The database engine was picked but its driver is not installed."""


class DatabaseExists(JubakoError):
    """Asked to make a database that is already there."""


class DatabaseMissing(JubakoError):
    """Asked to open a database that is not there."""


class TableMissing(JubakoError):
    """Asked for a table this database does not have."""


class BadName(JubakoError):
    """A table or field name we cannot use safely."""


class ImportProblem(JubakoError):
    """The spreadsheet could not be turned into a table."""


class LookupMissing(JubakoError):
    """Turning a field into a lookup: some of its values match no row of the other table."""

    def __init__(self, message: str, missing: list[str]) -> None:
        super().__init__(message)
        self.missing = missing
