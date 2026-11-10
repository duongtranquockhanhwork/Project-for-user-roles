"""Database access helpers.

Every query in the application goes through these helpers and passes user
input only as bound parameters (psycopg2 `%s` placeholders). SQL text is never
built by concatenating request data.
"""
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import g

_pool = None


def init_pool(config):
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=10,
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        connect_timeout=5,
        application_name="uni-records-web",
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def get_conn():
    """Connection bound to the current request (one transaction per request)."""
    if "db_conn" not in g:
        g.db_conn = _pool.getconn()
    return g.db_conn


def close_request_conn(exc=None):
    conn = g.pop("db_conn", None)
    if conn is None:
        return
    try:
        conn.rollback()  # anything not explicitly committed is discarded
    finally:
        _pool.putconn(conn)


@contextmanager
def separate_transaction():
    """A short independent transaction, committed even if the request fails.

    Used for audit records of rejected actions: the rejection must be logged
    although the request's own transaction is rolled back.
    """
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def query_all(sql, params=(), conn=None):
    with (conn or get_conn()).cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql, params=(), conn=None):
    with (conn or get_conn()).cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql, params=(), conn=None):
    with (conn or get_conn()).cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def commit():
    get_conn().commit()


def rollback():
    get_conn().rollback()


def init_app(app):
    init_pool(app.config["APP_CONFIG"])
    app.teardown_appcontext(close_request_conn)
