"""The backend chooser, and the SQL each engine builds.

A live PostgreSQL or MySQL server is not assumed here — those get exercised
by `scripts/smoke_remote.py`. What these tests pin down is everything that
can be checked without one: that the drivers import, that each engine maps
Jubako's five field types onto real column types, and that the
identifier quoting and parameter markers are the ones that engine wants.
"""

from __future__ import annotations

import pytest

from jubako.errors import BadName, JubakoError
from jubako.fields import BOOLEAN, DATE, INTEGER, LOOKUP, REAL, TEXT, Field
from jubako.storage import (
    BACKENDS,
    MYSQL,
    POSTGRES,
    SQLITE,
    backend_choice,
    create_database,
    normalise_backend,
    open_database,
)

ALL_FIELDS = [
    Field("name", TEXT),
    Field("age", INTEGER),
    Field("weight", REAL),
    Field("day", DATE),
    Field("ok", BOOLEAN),
]


def test_the_three_locked_backends_are_offered():
    assert [choice.key for choice in BACKENDS] == [SQLITE, POSTGRES, MYSQL]
    assert BACKENDS[0].needs_server is False
    assert all(choice.blurb and choice.title for choice in BACKENDS)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("sqlite", SQLITE),
        ("SQLite3", SQLITE),
        ("postgresql", POSTGRES),
        ("PG", POSTGRES),
        ("mariadb", MYSQL),
        (None, SQLITE),
    ],
)
def test_backend_names_people_type(typed, expected):
    assert normalise_backend(typed) == expected


def test_an_unknown_backend_is_refused():
    with pytest.raises(JubakoError, match="duckdb"):
        normalise_backend("duckdb")


def test_sqlite_is_the_default_and_always_ready():
    assert backend_choice("sqlite").driver_installed() is True


def test_server_backends_need_their_details(sandbox):
    with pytest.raises(JubakoError, match="which PostgreSQL database"):
        create_database(title="x", backend="postgres", connection={"host": "localhost"})
    with pytest.raises(JubakoError, match="which MySQL"):
        create_database(title="x", backend="mysql", connection={"host": "localhost"})
    with pytest.raises(JubakoError, match="sslmode"):
        open_database(backend="postgres", connection={"database": "d", "sslmode": "require"})


def test_sqlite_needs_somewhere_to_save(sandbox):
    with pytest.raises(JubakoError, match="where to save"):
        create_database(title="x", backend="sqlite")


# -- what each engine's SQL looks like -------------------------------------
#
# These drive the real backend classes without connecting, so the SQL they
# would send is checked exactly. `__new__` skips the constructor, which is
# the only part that needs a server.

def _bare(cls):
    return cls.__new__(cls)


def test_postgres_sql_shapes():
    psycopg = pytest.importorskip("psycopg")
    assert psycopg.__version__
    from jubako.storage.postgres import PostgresStorage, connection_string

    storage = _bare(PostgresStorage)
    assert storage.quote("pets") == '"pets"'
    assert storage.placeholder(0) == "%s"
    assert storage.primary_key_sql() == '"id" BIGSERIAL PRIMARY KEY'
    assert [storage.column_sql(f) for f in ALL_FIELDS] == [
        '"name" TEXT',
        '"age" BIGINT',
        '"weight" DOUBLE PRECISION',
        '"day" DATE',
        '"ok" BOOLEAN',
    ]
    with pytest.raises(BadName):
        storage.quote('pets"; DROP TABLE x --')

    assert connection_string(host="db", port=5433, database="d", user="u", password="p") == (
        "host=db port=5433 dbname=d user=u password=p"
    )
    assert connection_string(url="postgresql://u@h/d") == "postgresql://u@h/d"


def test_postgres_never_shows_the_password_back():
    pytest.importorskip("psycopg")
    from jubako.storage.postgres import _redact

    assert _redact("host=db password=hunter2 user=u") == "host=db password=*** user=u"
    assert _redact("postgresql://u:hunter2@host/db") == "postgresql://u:***@host/db"


def test_mysql_sql_shapes():
    pymysql = pytest.importorskip("pymysql")
    assert pymysql.__version__
    from jubako.storage.mysql import MySQLStorage

    storage = _bare(MySQLStorage)
    assert storage.quote("pets") == "`pets`"
    assert storage.placeholder(0) == "%s"
    assert storage.primary_key_sql() == "`id` BIGINT AUTO_INCREMENT PRIMARY KEY"
    assert [storage.column_sql(f) for f in ALL_FIELDS] == [
        "`name` TEXT",
        "`age` BIGINT",
        "`weight` DOUBLE",
        "`day` DATE",
        "`ok` TINYINT(1)",
    ]
    with pytest.raises(BadName):
        storage.quote("pets`; DROP TABLE x")


def test_every_backend_covers_every_field_type():
    pytest.importorskip("psycopg")
    pytest.importorskip("pymysql")
    from jubako.storage.mysql import _COLUMN_TYPES as MYSQL_TYPES
    from jubako.storage.postgres import _COLUMN_TYPES as PG_TYPES
    from jubako.storage.sqlite import _COLUMN_TYPES as SQLITE_TYPES

    for table in (SQLITE_TYPES, PG_TYPES, MYSQL_TYPES):
        assert set(table) == {TEXT, INTEGER, REAL, DATE, BOOLEAN, LOOKUP}
