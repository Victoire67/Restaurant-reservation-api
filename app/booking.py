"""Transactional reservation booking."""
from datetime import datetime

from psycopg2 import errors

from app.db import get_connection


class BookingError(Exception):
    """Base class for booking failures that can be shown to the customer."""


class TableNotFound(BookingError):
    pass


class PartyTooLarge(BookingError):
    pass


class TableUnavailable(BookingError):
    pass


def book_reservation(
    customer_id: int,
    table_id: int,
    start_time: datetime,
    end_time: datetime,
    party_size: int,
) -> int:
    """Book a table atomically and return the new reservation id.

    Runs as one transaction. The table row is locked first, so concurrent
    requests for the same table are processed one at a time.
    """
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time")
    if party_size <= 0:
        raise ValueError("party_size must be positive")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Lock the table row; other bookings for this table wait here until we finish
            cur.execute(
                "SELECT capacity FROM restaurant_tables WHERE id = %s FOR UPDATE",
                (table_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise TableNotFound(f"Table {table_id} does not exist")
            capacity = row[0]

            # 2. The party must fit at the table
            if party_size > capacity:
                raise PartyTooLarge(
                    f"Table {table_id} seats {capacity}, party size is {party_size}"
                )

            # 3. No active booking may overlap the requested time
            cur.execute(
                """
                SELECT 1 FROM reservations
                WHERE table_id = %s
                  AND status = 'booked'
                  AND start_time < %s
                  AND end_time > %s
                LIMIT 1
                """,
                (table_id, end_time, start_time),
            )
            if cur.fetchone() is not None:
                raise TableUnavailable(f"Table {table_id} is already booked at that time")

            # 4. Everything checks out: insert the reservation
            try:
                cur.execute(
                    """
                    INSERT INTO reservations (table_id, customer_id, party_size, start_time, end_time)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (table_id, customer_id, party_size, start_time, end_time),
                )
            except errors.ExclusionViolation:
                # Safety net from schema.sql caught an overlap the check above missed
                raise TableUnavailable(f"Table {table_id} is already booked at that time")
            return cur.fetchone()[0]


if __name__ == "__main__":
    # Manual demo against the seed data (re-run sql/seed.sql to reset before running again)
    from datetime import timedelta, timezone

    kigali = timezone(timedelta(hours=2))

    def at(hour, minute=0):
        return datetime(2026, 11, 15, hour, minute, tzinfo=kigali)

    # Table 1 (2 seats) is free at 19:00 -> should succeed
    new_id = book_reservation(customer_id=4, table_id=1, start_time=at(19), end_time=at(21), party_size=2)
    print("Booked, reservation id:", new_id)

    # Table 2 is already booked 19:00-21:00 in the seed -> should be refused
    try:
        book_reservation(customer_id=5, table_id=2, start_time=at(19, 30), end_time=at(20, 30), party_size=2)
    except BookingError as e:
        print("Refused:", e)

    # Party of 5 at table 1 (2 seats) -> should be refused
    try:
        book_reservation(customer_id=5, table_id=1, start_time=at(12), end_time=at(13), party_size=5)
    except BookingError as e:
        print("Refused:", e)
