"""Table availability: a PostgreSQL CTE query, cached in Redis per time slot.

Cache pattern: cache-aside.
    1. Look in Redis. Hit -> return it, Postgres is not touched.
    2. Miss -> ask Postgres, store the answer in Redis with a TTL, return it.

Invalidation: every restaurant has a version number in Redis, and that
number is part of every cache key. A successful booking increments it,
so all old answers for that restaurant stop being read and expire on their own.

Postgres stays the source of truth: book_reservation() always re-checks
availability under a row lock, so a stale cache can never cause a double booking.
"""
import json
import os
from datetime import datetime, timezone

import redis

from app.cache import get_redis
from app.db import get_connection

CACHE_TTL_SECONDS = int(os.getenv("AVAILABILITY_CACHE_TTL", "300"))

AVAILABLE_TABLES_QUERY = """
    WITH candidate_tables AS (
        -- Tables in this restaurant that are big enough for the party
        SELECT id, table_number, capacity
        FROM restaurant_tables
        WHERE restaurant_id = %(restaurant_id)s
          AND capacity >= %(party_size)s
    ),
    busy_tables AS (
        -- Candidate tables with an active booking overlapping the requested window
        SELECT DISTINCT table_id
        FROM reservations
        WHERE status = 'booked'
          AND start_time < %(end_time)s
          AND end_time   > %(start_time)s
          AND table_id IN (SELECT id FROM candidate_tables)
    )
    SELECT c.id, c.table_number, c.capacity
    FROM candidate_tables c
    WHERE NOT EXISTS (SELECT 1 FROM busy_tables b WHERE b.table_id = c.id)
    ORDER BY c.capacity, c.table_number
"""


def find_available_tables(restaurant_id, start_time, end_time, party_size):
    """Ask PostgreSQL directly (no cache) which tables are free."""
    params = {
        "restaurant_id": restaurant_id,
        "start_time": start_time,
        "end_time": end_time,
        "party_size": party_size,
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(AVAILABLE_TABLES_QUERY, params)
            rows = cur.fetchall()

    return [
        {"table_id": table_id, "table_number": number, "capacity": capacity}
        for table_id, number, capacity in rows
    ]


def get_available_tables(restaurant_id, start_time, end_time, party_size):
    """Free tables for a time slot, served from Redis when possible."""
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time")
    if party_size <= 0:
        raise ValueError("party_size must be positive")

    try:
        r = get_redis()
        # Read the version BEFORE querying Postgres: if a booking lands while we
        # query, it bumps the version and our (now stale) answer is never read.
        key = _cache_key(restaurant_id, _current_version(r, restaurant_id),
                         start_time, end_time, party_size)

        cached = r.get(key)
        if cached is not None:
            return json.loads(cached)

        tables = find_available_tables(restaurant_id, start_time, end_time, party_size)
        r.set(key, json.dumps(tables), ex=CACHE_TTL_SECONDS)
        return tables

    except redis.RedisError:
        # Redis is down: still answer correctly, just without the cache
        return find_available_tables(restaurant_id, start_time, end_time, party_size)


def invalidate_restaurant(restaurant_id):
    """Make every cached availability answer for this restaurant outdated.

    Call this only AFTER the booking transaction has committed.
    """
    try:
        get_redis().incr(_version_key(restaurant_id))
    except redis.RedisError:
        # The booking is already saved; a Redis failure must not undo that.
        # Worst case: old answers live until their TTL runs out.
        pass


# --- Key helpers ---------------------------------------------------------------

def _version_key(restaurant_id):
    return f"availability:version:{restaurant_id}"


def _current_version(r, restaurant_id):
    return int(r.get(_version_key(restaurant_id)) or 0)


def _cache_key(restaurant_id, version, start_time, end_time, party_size):
    # Same moment written in different time zones must give the same key
    start = _to_utc(start_time)
    end = _to_utc(end_time)
    return f"availability:{restaurant_id}:v{version}:{start}:{end}:party{party_size}"


def _to_utc(moment: datetime):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


if __name__ == "__main__":
    # Manual demo against the seed data
    from datetime import timedelta

    kigali = timezone(timedelta(hours=2))
    start = datetime(2026, 11, 15, 19, 30, tzinfo=kigali)
    end = datetime(2026, 11, 15, 20, 30, tzinfo=kigali)

    print("1st call (miss, from Postgres):", get_available_tables(1, start, end, 2))
    print("2nd call (hit, from Redis):    ", get_available_tables(1, start, end, 2))
