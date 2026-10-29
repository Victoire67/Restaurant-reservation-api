-- =====================================================================
-- Performance indexes. Run after schema.sql.
-- Re-runnable: IF NOT EXISTS skips indexes that are already there.
-- Measured effect: see docs/query_optimization.md (scripts/benchmark.py).
-- =====================================================================

-- Time slots: "is this table booked between X and Y?"
-- Used by the availability CTE and the overlap check in book_reservation().
-- Partial (WHERE status = 'booked'): cancelled/completed rows are never
-- searched for overlaps, so they are left out and the index stays smaller.
CREATE INDEX IF NOT EXISTS idx_reservations_table_time
    ON reservations (table_id, start_time, end_time)
    WHERE status = 'booked';

-- Table capacity: "tables in restaurant R with at least N seats"
-- restaurant_id first (equality), capacity second (range >=).
CREATE INDEX IF NOT EXISTS idx_tables_restaurant_capacity
    ON restaurant_tables (restaurant_id, capacity);

-- Location search: GiST is the index type that understands geometry,
-- so ST_DWithin can skip restaurants that are far away.
CREATE INDEX IF NOT EXISTS idx_restaurants_location
    ON restaurants USING gist (location);

-- Latest reviews of one restaurant (get_restaurant_reviews): finds only that
-- restaurant's rows, and because the index order matches the ORDER BY, a
-- restaurant with many reviews can be read newest-first and stop at LIMIT.
-- (The RANK() query is NOT helped by any index: it aggregates every review,
-- and reading the whole table sequentially is the cheapest way to do that.)
CREATE INDEX IF NOT EXISTS idx_reviews_restaurant_latest
    ON reviews (restaurant_id, created_at DESC, id DESC);

-- Refresh planner statistics so the new indexes are considered right away
ANALYZE restaurants;
ANALYZE restaurant_tables;
ANALYZE reservations;
ANALYZE reviews;
