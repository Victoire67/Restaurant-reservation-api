"""PostgreSQL connection pool shared by the whole application."""
import os
import threading
from contextlib import contextmanager

from dotenv import load_dotenv
from psycopg2.pool import ThreadedConnectionPool

load_dotenv()

_pool = None
_pool_lock = threading.Lock()


def get_pool():
    """Create the pool on first use, then return the same pool every time."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:  # another thread may have created it while we waited
                _pool = ThreadedConnectionPool(
                    minconn=int(os.getenv("PG_POOL_MIN", "1")),
                    maxconn=int(os.getenv("PG_POOL_MAX", "20")),
                    host=os.getenv("POSTGRES_HOST"),
                    port=os.getenv("POSTGRES_PORT"),
                    user=os.getenv("POSTGRES_USER"),
                    password=os.getenv("POSTGRES_PASSWORD"),
                    dbname=os.getenv("POSTGRES_DB"),
                )
    return _pool


@contextmanager
def get_connection():
    """Borrow a connection from the pool as one transaction.

    Commits if the block finishes normally, rolls back if it raises,
    and always gives the connection back to the pool.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool():
    """Close every connection in the pool (call on shutdown)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


if __name__ == "__main__":
    # Quick self-check: borrow a connection and count the cities
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM cities;")
            print("Pool works. Cities in database:", cur.fetchone()[0])
    close_pool()
