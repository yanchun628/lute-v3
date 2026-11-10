"""Database assertions.

This module is "registered" to pytest in ./__init__.py
to get nicer assertion details.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.sql import text

from lute.config.app_config import AppConfig


def __sqlite_uri():
    """
    Get the application Sqlite URL from the config file.
    """
    this_files_dir = os.path.dirname(os.path.realpath(__file__))
    conf_file = os.path.normpath(
        os.path.join(this_files_dir, "..", "lute", "config", "config.yml")
    )
    ac = AppConfig(conf_file)
    return ac.sqliteconnstring


def _query_rows(sql):
    """
    Run sql and return all rows, closing the connection afterwards
    (an open connection stops Windows from deleting the test db).
    """
    engine = create_engine(__sqlite_uri())
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql)).fetchall()
    finally:
        engine.dispose()


def assert_sql_result(sql, expected, msg=""):
    """
    Checks sql results (stringized) against expected.

    e.g. with sql = "select 1, 2", expected would be [ "1; 2" ]

    This replaces all zero-width strings with '/'
    """
    result = _query_rows(sql)
    zws = "\u200B"  # zero-width space
    actual = ["; ".join([f"{s}".replace(zws, "/") for s in row]) for row in result]
    assert actual == expected, msg


def assert_record_count_equals(sql, expected, message=""):
    """
    Checks count of records of sql results (stringized) against expected.

    e.g. with sql = "select 1, 2", expected would be 1
    """

    # Check if the SQL query is a SELECT statement
    if not sql.lower().startswith("select"):
        sql = f"SELECT * FROM {sql}"

    result = _query_rows(sql)

    actual = ["; ".join([f"{s}" for s in row]) for row in result]

    if len(actual) != expected:
        message += f" ... got data:\n\n{actual}\n"

    assert len(actual) == expected, message
