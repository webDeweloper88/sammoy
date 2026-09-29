from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings


pool = ConnectionPool(settings.database_url, min_size=1, max_size=8, open=False)


def open_pool() -> None:
    pool.open(wait=True)


def close_pool() -> None:
    pool.close()


@contextmanager
def db() -> Iterator[Connection]:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        yield conn
