"""Tests for the availability query and its Redis cache (run against the seed data)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.availability import find_available_tables, get_available_tables
from app.booking import book_reservation
from app.cache import get_redis
from app.db import close_pool, get_connection

SEED_FILE = Path(__file__).resolve().parent.parent / "sql" / "seed.sql"
KIGALI = timezone(timedelta(hours=2))


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=KIGALI)


def table_ids(tables):
    return [t["table_id"] for t in tables]


@pytest.fixture(autouse=True)
def fresh_data():
    """Reset Postgres to the seed data and empty Redis before every test."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SEED_FILE.read_text(encoding="utf-8"))
    get_redis().flushdb()


@pytest.fixture(scope="session", autouse=True)
def pool_cleanup():
    """Close the connection pool once all tests have finished."""
    yield
    close_pool()


def cached_keys():
    return [k for k in get_redis().keys("availability:*") if ":version:" not in k]


# --- The CTE query (Postgres only) ------------------------------------------

def test_busy_tables_are_excluded():
    # Restaurant 1 at 19:30-20:30: table 2 (19-21) and table 3 (20-22) are booked
    tables = find_available_tables(1, at(15, 19, 30), at(15, 20, 30), 2)

    assert table_ids(tables) == [1]


def test_tables_too_small_are_excluded():
    # Party of 4 at a quiet time: table 1 only seats 2
    tables = find_available_tables(1, at(15, 12), at(15, 13), 4)

    assert table_ids(tables) == [2, 3]


def test_cancelled_booking_does_not_block():
    # Cancel table 2's active booking; only its already-cancelled row (19:30-21:00) remains
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reservations SET status = 'cancelled' WHERE id = 1")

    tables = find_available_tables(1, at(15, 19, 30), at(15, 20, 30), 2)

    assert 2 in table_ids(tables)


# --- The Redis cache ---------------------------------------------------------

def test_first_call_stores_the_answer_in_redis():
    assert cached_keys() == []

    get_available_tables(1, at(15, 12), at(15, 13), 2)

    assert len(cached_keys()) == 1


def test_second_call_is_served_from_redis():
    first = get_available_tables(1, at(15, 12), at(15, 13), 2)

    # Change Postgres behind the cache's back (no invalidation)...
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reservations (table_id, customer_id, party_size, start_time, end_time)
                VALUES (1, 4, 2, %s, %s)
                """,
                (at(15, 12), at(15, 13)),
            )

    # ...the cached answer comes back unchanged, proving Postgres was not asked
    assert get_available_tables(1, at(15, 12), at(15, 13), 2) == first


def test_different_party_sizes_use_different_keys():
    get_available_tables(1, at(15, 12), at(15, 13), 2)
    get_available_tables(1, at(15, 12), at(15, 13), 4)

    assert len(cached_keys()) == 2


def test_same_moment_in_another_time_zone_hits_the_same_key():
    utc_start = at(15, 12).astimezone(timezone.utc)
    utc_end = at(15, 13).astimezone(timezone.utc)

    get_available_tables(1, at(15, 12), at(15, 13), 2)
    get_available_tables(1, utc_start, utc_end, 2)

    assert len(cached_keys()) == 1


# --- Invalidation: the key test ------------------------------------------------

def test_booking_invalidates_the_cached_answer():
    before = get_available_tables(1, at(15, 12), at(15, 13), 2)
    assert 1 in table_ids(before)

    book_reservation(4, 1, at(15, 12), at(15, 13), 2)

    after = get_available_tables(1, at(15, 12), at(15, 13), 2)
    assert 1 not in table_ids(after)


def test_booking_does_not_invalidate_other_restaurants():
    get_available_tables(2, at(15, 12), at(15, 13), 2)

    book_reservation(4, 1, at(15, 12), at(15, 13), 2)  # restaurant 1

    # Restaurant 2's version is unchanged, so its answer is still a cache hit
    get_available_tables(2, at(15, 12), at(15, 13), 2)
    assert len(cached_keys()) == 1
