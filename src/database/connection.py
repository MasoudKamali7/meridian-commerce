"""
Meridian Commerce — Phase 3: Database Connection

A thin, explicit connection helper — no ORM. This is a small enough project
that raw SQL through psycopg2 (already used in Phase 2's load_data.py) stays
readable and avoids adding an ORM dependency just for a handful of queries.
"""

from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from ..config import Config


class DatabaseError(Exception):
    """Wraps any psycopg2 error so callers (classifier/pipeline) only need
    to catch one exception type from the database layer."""
    pass


@contextmanager
def get_connection(config: Config):
    conn = None
    try:
        conn = psycopg2.connect(
            host=config.db_host,
            port=config.db_port,
            dbname=config.db_name,
            user=config.db_user,
            password=config.db_password,
        )
        yield conn
    except psycopg2.Error as e:
        raise DatabaseError(str(e)) from e
    finally:
        if conn is not None:
            conn.close()


@contextmanager
def get_cursor(conn, dict_cursor: bool = True):
    cursor_factory = psycopg2.extras.RealDictCursor if dict_cursor else None
    cur = conn.cursor(cursor_factory=cursor_factory)
    try:
        yield cur
    except psycopg2.Error as e:
        conn.rollback()
        raise DatabaseError(str(e)) from e
    finally:
        cur.close()
