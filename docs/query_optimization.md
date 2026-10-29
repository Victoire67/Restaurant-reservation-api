# Query optimization

How the indexes in [`sql/indexes.sql`](../sql/indexes.sql) were chosen and what
they changed, measured with `EXPLAIN (ANALYZE, BUFFERS)` on a realistic dataset.

Full plans: [`benchmark_results.md`](benchmark_results.md) · Reproduce: `python -m scripts.benchmark`

## Method

1. Load [`sql/bulk_seed.sql`](../sql/bulk_seed.sql): 5 000 restaurants in 50 cities,
   40 000 tables, ~720 000 reservations, 100 000 reviews. The small development
   seed is useless here: on a few rows Postgres always picks a sequential scan.
2. Drop the performance indexes, `ANALYZE`, run each query 7 times, keep the median.
3. Run `sql/indexes.sql` (creates the indexes and `ANALYZE`s), measure again.

The queries measured are the exact SQL strings the application runs
(imported from `app/`), not hand-written copies.

## Results

| Query | Before | After | Speed-up | Buffers read |
|---|---:|---:|---:|---:|
| Availability CTE | 0.660 ms | 0.181 ms | 3.6x | 117 → 29 |
| Location search, 10 km | 24.567 ms | 0.296 ms | 83x | 92 → 20 |
| Latest 20 reviews of a restaurant | 14.381 ms | 0.101 ms | 142x | 637 → 21 |
| RANK() per city | 146.303 ms | 138.046 ms | none (noise) | 715 → 715 |

Timings move a little between runs on a laptop; **buffers read** is the more
stable measure of how much work each plan does.

## Query by query

### 1. Availability CTE — `idx_reservations_table_time`, `idx_tables_restaurant_capacity`

```sql
CREATE INDEX idx_reservations_table_time
    ON reservations (table_id, start_time, end_time) WHERE status = 'booked';
CREATE INDEX idx_tables_restaurant_capacity
    ON restaurant_tables (restaurant_id, capacity);
```

**Before.** The baseline was already not a full scan: the exclusion constraint
`excl_reservations_no_overlap` creates its own GiST index, and the planner used
it to find each table's reservations. But that index only matched on `table_id`;
the time window was checked afterwards as a `Filter`, which threw away 14 rows
per table (`Rows Removed by Filter: 14`). For tables, the unique index on
`(restaurant_id, table_number)` found the restaurant, then capacity was filtered.

**After.** Both conditions moved into `Index Cond`:
- reservations: `table_id = … AND start_time < … AND end_time > …`, so only the
  overlapping rows are touched (heap blocks 88 → 3);
- tables: `restaurant_id = … AND capacity >= …` in one index range.

**Design choices.**
- Column order: the equality column (`table_id`, `restaurant_id`) first, the
  range columns after. A B-tree can only use a range on the column right after
  the equality ones.
- Partial index `WHERE status = 'booked'`: cancelled and completed reservations
  never block a table, so they are left out of the index. It is smaller, and the
  query's `status = 'booked'` lets the planner use it.
- The same index serves the overlap check inside `book_reservation()`, which has
  the same `WHERE` shape, so the transaction holds its row lock for less time.

### 2. Location search — `idx_restaurants_location` (GiST)

```sql
CREATE INDEX idx_restaurants_location ON restaurants USING gist (location);
```

**Before.** `Seq Scan on restaurants`: `ST_DWithin` was computed for all 5 000
restaurants and 4 985 were thrown away.

**After.** `Index Scan using idx_restaurants_location` with
`Index Cond: location && _st_expand(point, 10000)`. A B-tree cannot index 2-D
space; GiST stores bounding boxes, so PostGIS first asks the index for points
inside a box around the search circle (18 candidates), then checks the exact
distance only on those (3 removed).

### 3. Latest reviews of a restaurant — `idx_reviews_restaurant_latest`

```sql
CREATE INDEX idx_reviews_restaurant_latest
    ON reviews (restaurant_id, created_at DESC, id DESC);
```

**Before.** Seq scan of all 100 000 reviews (`Rows Removed by Filter: 99982`),
then a sort, to return 18 rows.

**After.** `Bitmap Index Scan on idx_reviews_restaurant_latest`: only this
restaurant's 18 rows are read (18 heap blocks), then sorted in memory. With so
few rows the planner prefers that over walking the index in order. For a
restaurant with thousands of reviews, the `created_at DESC, id DESC` columns let
Postgres read the index already in `ORDER BY` order and stop after `LIMIT` rows,
with no sort at all.

### 4. RANK() per city — no index helps, and that is the correct result

The plan is identical before and after: `Seq Scan on reviews` → `HashAggregate`
→ `WindowAgg`. The query computes an average over **every** review, so every row
must be read anyway, and a sequential scan is the cheapest way to read a whole
table. An earlier version of `indexes.sql` had `reviews (restaurant_id) INCLUDE (rating)`
for this query; the benchmark showed the planner ignored it (same 715 buffers),
so it was replaced with the index in section 3, which does pay off.

If ranking had to be instant at much larger scale, the next step would be to
precompute it rather than index it: a `MATERIALIZED VIEW` of per-restaurant
averages refreshed periodically, or cached in Redis like availability.

## Trade-offs

- Every index slows down `INSERT`s a little and uses disk. Only indexes that a
  measured query uses were kept.
- `ANALYZE` after creating indexes matters: without fresh statistics the
  planner may not know the index is selective.
- Availability is also cached in Redis (`app/availability.py`), so the indexed
  query only runs on a cache miss.
