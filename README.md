# Restaurant Reservation & Review System — Backend

A multi-restaurant booking backend built on three databases, each used for what
it is good at:

| Store | Holds | Why |
|---|---|---|
| **PostgreSQL** (+ PostGIS) | cities, restaurants, tables, customers, reservations, review ratings | Relational data that must stay consistent: transactions, constraints, joins, window functions, spatial index |
| **Redis** | cached table availability per time slot | The most frequent read ("what's free at 19:00?") answered from memory |
| **MongoDB** | long-form review text | Free-shaped, possibly long documents that are only ever read whole |

Menus and opening hours are stored as **JSONB** in `restaurants`: their shape
varies per restaurant and they are always read as one piece.

## Quick start

Requirements: Docker, Python 3.11+, [Poetry](https://python-poetry.org/).

```powershell
# 1. Configuration
Copy-Item .env.example .env          # then set the passwords

# 2. Databases (PostgreSQL/PostGIS, Redis, MongoDB)
docker compose up -d

# 3. Python dependencies
poetry install

# 4. Schema, indexes and development data
Get-Content sql/schema.sql  | docker compose exec -T postgres psql -U restaurant -d restaurant_db
Get-Content sql/indexes.sql | docker compose exec -T postgres psql -U restaurant -d restaurant_db
Get-Content sql/seed.sql    | docker compose exec -T postgres psql -U restaurant -d restaurant_db

# 5. Check everything is reachable, then run the tests
poetry run python -m app.check_connections
poetry run pytest -v
```

The tests reset PostgreSQL to `sql/seed.sql` and empty Redis / the Mongo
`feedback` collection before each test, so run them against a development
database only.

Each module also has a small demo: `poetry run python -m app.booking`,
`app.availability`, `app.reviews`, `app.analytics`.

## Project layout

```text
app/
  db.py             PostgreSQL connection pool (psycopg2 ThreadedConnectionPool)
  cache.py          Redis client
  mongo.py          MongoDB client + feedback collection index
  booking.py        Transactional reservation booking
  availability.py   Availability CTE + Redis cache-aside
  reviews.py        Reviews split across PostgreSQL and MongoDB
  analytics.py      RANK() per city, GiST location search
sql/
  schema.sql        3NF schema, constraints, extensions
  indexes.sql       Performance indexes
  seed.sql          Small predictable dataset (dev + tests)
  bulk_seed.sql     ~900k rows for benchmarking
scripts/
  benchmark.py      EXPLAIN ANALYZE before/after indexes
  dev.ps1           psql shortcuts (`show reservations`, ...)
tests/              pytest suites, one per module
docs/
  er_diagram.md          ER diagram (Mermaid)
  query_optimization.md  Index choices and measured effect
  benchmark_results.md   Full EXPLAIN ANALYZE plans
```

## Schema (3NF)

Six tables: `cities`, `restaurants`, `restaurant_tables`, `customers`,
`reservations`, `reviews`. See the [ER diagram](docs/er_diagram.md).

- **`cities` is its own table** so "rank per city" groups on an id, not on
  free text that could be spelled two ways.
- **`reservations` has no `restaurant_id`**: it is derived through `table_id`.
  Storing it twice would let the two disagree (a transitive dependency, which 3NF forbids).
- **Constraints enforce the rules in the database itself**: party size and
  capacity `> 0`, `end_time > start_time`, rating 1–5, allowed status values,
  unique table numbers per restaurant, unique customer e-mail.
- **No double booking, ever**: an exclusion constraint forbids two `booked`
  reservations on the same table with overlapping time ranges:
  `EXCLUDE USING gist (table_id WITH =, tstzrange(start_time, end_time, '[)') WITH &&) WHERE (status = 'booked')`.
  `'[)'` means a booking ending at 21:00 does not clash with one starting at 21:00.

## Transactional booking — `app/booking.py`

`book_reservation(customer_id, table_id, start_time, end_time, party_size)`
runs as **one transaction** (commit on success, rollback on any error):

1. `SELECT … FROM restaurant_tables WHERE id = %s FOR UPDATE` — locks the table row.
   Concurrent bookings for the same table now wait in line instead of racing.
2. Refuse if the party is larger than the table's capacity.
3. Refuse if an active booking overlaps the requested time.
4. Insert the reservation. If the exclusion constraint still fires, it is
   reported as `TableUnavailable` too.
5. After the commit, invalidate the restaurant's cached availability in Redis.

All SQL uses **parameterized queries** (`%s` / `%(name)s`); values are never
formatted into SQL strings.

The key test, `test_concurrent_bookings_for_same_slot_only_one_succeeds`, starts 10
threads at the same instant, all booking the same table and slot. Exactly
one succeeds.

## Redis availability cache — `app/availability.py`

**Cache-aside**: look in Redis → on a miss, run the availability CTE in
PostgreSQL, store the answer with a TTL (`AVAILABILITY_CACHE_TTL`, default 300 s).

Key: `availability:{restaurant}:v{version}:{start_utc}:{end_utc}:party{n}`

**Invalidation by version number.** Each restaurant has a counter
`availability:version:{restaurant}` that is part of every key. A successful
booking increments it, so every old answer for that restaurant stops being read
and expires on its own. That needs no key scanning or pattern deletes.

- The version is read *before* querying Postgres, so an answer computed while a
  booking commits is stored under the old version and never served.
- Times are normalized to UTC so the same moment in two time zones shares one key.
- If Redis is down, the query falls back to PostgreSQL.
- **PostgreSQL stays the source of truth**: booking always re-checks under the row
  lock, so a stale cache can at worst show a table that turns out to be taken.
  It can never cause a double booking.

## Reviews across two databases — `app/reviews.py`

The rating lives in PostgreSQL (needed by `AVG` and `RANK()`), the text in
MongoDB, linked by `reviews.mongo_feedback_id`.

The two databases can't share a transaction, so `submit_review()` writes MongoDB
first, then PostgreSQL. If the PostgreSQL insert fails (e.g. unknown restaurant),
the Mongo document is deleted again, a *compensating action*, so no orphaned text
is left behind. `get_restaurant_reviews()` loads all texts in one `$in` query,
not one query per review.

## Analytical queries — `app/analytics.py`, `app/availability.py`

- **Rank restaurants per city**: a CTE computes each restaurant's average rating,
  then `RANK() OVER (PARTITION BY city_id ORDER BY avg_rating DESC)`. Equal
  averages share a rank. `min_reviews` filters out barely-reviewed places.
- **Available tables (CTE)**: `candidate_tables` (big enough for the party)
  minus `busy_tables` (an active booking overlaps the window).
- **Location search**: `ST_DWithin` on a `GEOGRAPHY` column (metres), sorted by
  distance, served by a GiST index.

## Optimization

Indexes in [`sql/indexes.sql`](sql/indexes.sql), measured with `EXPLAIN (ANALYZE, BUFFERS)`
on ~900k rows (`poetry run python -m scripts.benchmark`):

| Query | Before | After | Index |
|---|---:|---:|---|
| Availability CTE | 0.660 ms | 0.181 ms | `reservations (table_id, start_time, end_time) WHERE status='booked'`, `restaurant_tables (restaurant_id, capacity)` |
| Location search | 24.567 ms | 0.296 ms | GiST on `restaurants.location` |
| Latest reviews | 14.381 ms | 0.101 ms | `reviews (restaurant_id, created_at DESC, id DESC)` |
| RANK() per city | 146 ms | 138 ms | none: it reads every review, so a seq scan is optimal |

The reasoning behind each index, including why the ranking query is
deliberately left unindexed, is in [docs/query_optimization.md](docs/query_optimization.md).

## Requirements checklist

| Requirement | Where |
|---|---|
| 3NF schema: restaurants, tables, customers, reservations, reviews | `sql/schema.sql` |
| ER diagram | `docs/er_diagram.md` |
| psycopg2 connection pooling | `app/db.py` |
| Atomic booking: check availability, insert only if free | `app/booking.py` |
| Parameterized queries | all of `app/` |
| JSONB menus and opening hours | `restaurants.menu`, `restaurants.opening_hours` |
| Redis cache of availability per time slot | `app/availability.py` |
| MongoDB long-form reviews | `app/reviews.py`, `app/mongo.py` |
| RANK() restaurants by average score per city | `app/analytics.py` |
| CTE for available tables at a time + party size | `app/availability.py` |
| EXPLAIN ANALYZE optimization | `scripts/benchmark.py`, `docs/query_optimization.md` |
| Index on time slots and table capacity | `sql/indexes.sql` |
| GiST index for location search | `sql/indexes.sql` |
