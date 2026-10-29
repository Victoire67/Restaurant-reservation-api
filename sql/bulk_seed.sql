-- =====================================================================
-- Bulk data for EXPLAIN ANALYZE benchmarks (scripts/benchmark.py).
-- Replaces ALL data. Run sql/seed.sql afterwards to get the small
-- development dataset back (the tests do this automatically).
--
-- Size: 50 cities, 5 000 restaurants, 40 000 tables, 20 000 customers,
--       ~720 000 reservations, 100 000 reviews.
-- setseed() makes random() repeatable, so every run builds the same data.
-- =====================================================================

BEGIN TRANSACTION;

TRUNCATE reviews, reservations, restaurant_tables, restaurants, customers, cities
    RESTART IDENTITY CASCADE;

SELECT setseed(0.42);

-- Cities ------------------------------------------------------------------
INSERT INTO cities (name, country)
SELECT 'City ' || g, 'Country ' || (g % 10 + 1)
FROM generate_series(1, 50) AS g;

-- Restaurants: 100 per city, scattered up to ~20 km around the city centre --
-- The centre is derived from the city id so cities sit far apart.
INSERT INTO restaurants (city_id, name, address, location)
SELECT city_id,
       'Restaurant ' || g,
       g || ' Main Street',
       ST_MakePoint(
           -170 + (city_id * 37 % 340) + (random() - 0.5) * 0.4,   -- longitude
           -50  + (city_id * 17 % 100) + (random() - 0.5) * 0.4    -- latitude
       )::geography
FROM (SELECT g, (g - 1) % 50 + 1 AS city_id FROM generate_series(1, 5000) AS g) AS r;

-- Tables: 8 per restaurant with a realistic mix of sizes ----------------------
INSERT INTO restaurant_tables (restaurant_id, table_number, capacity)
SELECT r.id, t.n, (ARRAY[2, 2, 4, 4, 4, 6, 8, 10])[t.n]
FROM restaurants r
CROSS JOIN generate_series(1, 8) AS t(n);

-- Customers -----------------------------------------------------------------
INSERT INTO customers (full_name, email)
SELECT 'Customer ' || g, 'customer' || g || '@example.com'
FROM generate_series(1, 20000) AS g;

-- Reservations: 30 two-hour slots per table, every 3 hours from 1 Nov 2026.
-- About 60% of slots are taken; 1 in 10 of those is cancelled.
-- Slots never overlap, so the exclusion constraint is always satisfied.
INSERT INTO reservations (table_id, customer_id, party_size, start_time, end_time, status)
SELECT t.id,
       1 + floor(random() * 20000)::int,
       1 + floor(random() * t.capacity)::int,
       slot_start,
       slot_start + interval '2 hours',
       CASE WHEN random() < 0.1 THEN 'cancelled' ELSE 'booked' END
FROM restaurant_tables t
CROSS JOIN LATERAL (
    SELECT timestamptz '2026-11-01 10:00+00' + s * interval '3 hours' AS slot_start
    FROM generate_series(0, 29) AS s
) AS slots
WHERE random() < 0.6;

-- Reviews: each restaurant gets its own "quality" so averages differ ----------
-- created_at is spread over the past year so "latest reviews" has an order to use.
INSERT INTO reviews (restaurant_id, customer_id, rating, created_at)
SELECT restaurant_id,
       1 + floor(random() * 20000)::int,
       LEAST(5, GREATEST(1, round(quality + (random() - 0.5) * 2)))::smallint,
       now() - random() * interval '365 days'
FROM (
    SELECT 1 + floor(random() * 5000)::int AS restaurant_id
    FROM generate_series(1, 100000)
) AS picks
JOIN (
    SELECT id, 1.5 + random() * 3.5 AS quality FROM restaurants
) AS q ON q.id = picks.restaurant_id;

COMMIT;

ANALYZE;
