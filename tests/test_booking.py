"""Tests for the transactional booking logic (run against the seed data)."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.booking import PartyTooLarge, TableNotFound, TableUnavailable, book_reservation
from app.db import close_pool, get_connection

SEED_FILE = Path(__file__).resolve().parent.parent / "sql" / "seed.sql"
KIGALI = timezone(timedelta(hours=2))


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=KIGALI)


@pytest.fixture(autouse=True)
def fresh_data():
    """Reset the database to the seed data before every test."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SEED_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session", autouse=True)
def pool_cleanup():
    """Close the connection pool once all tests have finished."""
    yield
    close_pool()


def count_booked(table_id, start, end):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM reservations
                WHERE table_id = %s AND status = 'booked'
                  AND start_time < %s AND end_time > %s
                """,
                (table_id, end, start),
            )
            return cur.fetchone()[0]


# --- Normal behaviour -------------------------------------------------------

def test_booking_a_free_table_succeeds():
    new_id = book_reservation(4, 1, at(15, 19), at(15, 21), 2)

    assert isinstance(new_id, int)
    assert count_booked(1, at(15, 19), at(15, 21)) == 1


def test_back_to_back_booking_is_allowed():
    # Table 2 is booked 19:00-21:00 in the seed; 21:00-23:00 must still be free
    book_reservation(4, 2, at(15, 21), at(15, 23), 2)

    assert count_booked(2, at(15, 21), at(15, 23)) == 1


def test_cancelled_booking_does_not_block_the_table():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reservations SET status = 'cancelled' WHERE id = 1")

    book_reservation(4, 2, at(15, 19), at(15, 21), 2)

    assert count_booked(2, at(15, 19), at(15, 21)) == 1


# --- Refusals ---------------------------------------------------------------

def test_overlapping_booking_is_refused():
    with pytest.raises(TableUnavailable):
        book_reservation(5, 2, at(15, 19, 30), at(15, 20, 30), 2)


def test_party_too_large_is_refused():
    with pytest.raises(PartyTooLarge):
        book_reservation(5, 1, at(15, 12), at(15, 13), 5)


def test_unknown_table_is_refused():
    with pytest.raises(TableNotFound):
        book_reservation(5, 999, at(15, 12), at(15, 13), 2)


def test_end_before_start_is_refused():
    with pytest.raises(ValueError):
        book_reservation(5, 1, at(15, 21), at(15, 19), 2)


def test_refused_booking_saves_nothing():
    before = count_booked(2, at(15, 0), at(16, 0))

    with pytest.raises(TableUnavailable):
        book_reservation(5, 2, at(15, 19, 30), at(15, 20, 30), 2)

    assert count_booked(2, at(15, 0), at(16, 0)) == before


# --- Concurrency: the key test ----------------------------------------------

def test_concurrent_bookings_for_same_slot_only_one_succeeds():
    attempts = 10
    start_line = threading.Barrier(attempts)

    def attempt(i):
        start_line.wait()  # every thread waits here, then all go at once
        try:
            return book_reservation(i % 5 + 1, 1, at(20, 19), at(20, 21), 2)
        except TableUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(pool.map(attempt, range(attempts)))

    successes = [r for r in results if r is not None]
    assert len(successes) == 1
    assert count_booked(1, at(20, 19), at(20, 21)) == 1
