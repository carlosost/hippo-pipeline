# Fixture for ADR-009's zero-dependency rule. Never imported, only AST-parsed.
import polars as pl
from duckdb import connect


def f():
    return connect(), pl
