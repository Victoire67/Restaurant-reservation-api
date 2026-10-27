-- =====================================================================
-- Seed data: small, predictable dataset for development and Day 2 tests.
-- Re-runnable: empties every table and resets ids to 1 first.
-- =====================================================================

BEGIN TRANSACTION;

-- 1. Reset ---------------------------------------------------------------
TRUNCATE reviews, reservations, restaurant_tables, restaurants, customers, cities
    RESTART IDENTITY CASCADE;

-- 2. Cities (ids 1-3) ----------------------------------------------------
INSERT INTO cities (name, country) VALUES
    ('Kigali',  'Rwanda'),   -- id 1
    ('Nairobi', 'Kenya'),    -- id 2
    ('Paris',   'France');   -- id 3

-- 3. Restaurants (ids 1-4) -----------------------------------------------
-- ST_MakePoint takes LONGITUDE first, then LATITUDE.
INSERT INTO restaurants (city_id, name, address, phone, location, menu, opening_hours) VALUES
    (1, 'Ikirezi Bistro', 'KN 4 Ave, Kigali', '+250788000001',
        ST_MakePoint(30.0619, -1.9441)::geography,
        '{"currency": "RWF",
          "sections": [
            {"name": "Mains",    "items": [{"name": "Goat brochettes", "price": 6000, "vegan": false},
                                           {"name": "Bean stew",       "price": 4000, "vegan": true}]},
            {"name": "Desserts", "items": [{"name": "Banana fritters", "price": 2500, "vegan": true}]}
          ]}'::jsonb,
        '{"mon": {"open": "11:00", "close": "22:00"}, "tue": {"open": "11:00", "close": "22:00"},
          "wed": {"open": "11:00", "close": "22:00"}, "thu": {"open": "11:00", "close": "22:00"},
          "fri": {"open": "11:00", "close": "23:30"}, "sat": {"open": "11:00", "close": "23:30"},
          "sun": null}'::jsonb),                                                   -- id 1

    (1, 'Lake Kivu Kitchen', 'KG 7 Ave, Kigali', '+250788000002',
        ST_MakePoint(30.0890, -1.9536)::geography,
        '{"currency": "RWF",
          "sections": [
            {"name": "Mains", "items": [{"name": "Grilled tilapia", "price": 9000, "vegan": false},
                                        {"name": "Veggie platter",  "price": 5500, "vegan": true}]}
          ]}'::jsonb,
        '{"mon": null, "tue": {"open": "12:00", "close": "22:00"},
          "wed": {"open": "12:00", "close": "22:00"}, "thu": {"open": "12:00", "close": "22:00"},
          "fri": {"open": "12:00", "close": "23:00"}, "sat": {"open": "12:00", "close": "23:00"},
          "sun": {"open": "12:00", "close": "21:00"}}'::jsonb),                     -- id 2

    (2, 'Savanna Table', 'Kenyatta Ave, Nairobi', '+254700000003',
        ST_MakePoint(36.8172, -1.2864)::geography,
        '{"currency": "KES",
          "sections": [
            {"name": "Mains", "items": [{"name": "Nyama choma", "price": 1200, "vegan": false},
                                        {"name": "Sukuma wiki", "price": 450,  "vegan": true}]}
          ]}'::jsonb,
        '{"mon": {"open": "10:00", "close": "22:00"}, "tue": {"open": "10:00", "close": "22:00"},
          "wed": {"open": "10:00", "close": "22:00"}, "thu": {"open": "10:00", "close": "22:00"},
          "fri": {"open": "10:00", "close": "23:00"}, "sat": {"open": "10:00", "close": "23:00"},
          "sun": {"open": "10:00", "close": "20:00"}}'::jsonb),                     -- id 3

    (3, 'Le Petit Jardin', '12 Rue de Rivoli, Paris', '+33100000004',
        ST_MakePoint(2.3522, 48.8566)::geography,
        '{"currency": "EUR",
          "sections": [
            {"name": "Entrees", "items": [{"name": "Onion soup",   "price": 9,  "vegan": false}]},
            {"name": "Mains",   "items": [{"name": "Ratatouille",  "price": 18, "vegan": true},
                                          {"name": "Coq au vin",   "price": 24, "vegan": false}]}
          ]}'::jsonb,
        '{"mon": null, "tue": {"open": "18:00", "close": "23:00"},
          "wed": {"open": "18:00", "close": "23:00"}, "thu": {"open": "18:00", "close": "23:00"},
          "fri": {"open": "18:00", "close": "23:30"}, "sat": {"open": "18:00", "close": "23:30"},
          "sun": null}'::jsonb);                                                   -- id 4

-- 4. Tables (ids 1-10) ----------------------------------------------------
INSERT INTO restaurant_tables (restaurant_id, table_number, capacity) VALUES
    (1, 1, 2),   -- id 1
    (1, 2, 4),   -- id 2
    (1, 3, 6),   -- id 3
    (2, 1, 2),   -- id 4
    (2, 2, 4),   -- id 5
    (3, 1, 2),   -- id 6
    (3, 2, 4),   -- id 7
    (3, 3, 8),   -- id 8
    (4, 1, 4),   -- id 9
    (4, 2, 6);   -- id 10

-- 5. Customers (ids 1-5) --------------------------------------------------
INSERT INTO customers (full_name, email, phone) VALUES
    ('Alice Uwase',    'alice@example.com', '+250788100001'),   -- id 1
    ('Brian Otieno',   'brian@example.com', '+254700100002'),   -- id 2
    ('Claire Martin',  'claire@example.com', NULL),             -- id 3
    ('David Mugisha',  'david@example.com', '+250788100004'),   -- id 4
    ('Esther Wanjiru', 'esther@example.com', '+254700100005');  -- id 5

-- 6. Existing reservations (ids 1-3) --------------------------------------
-- Times include the time-zone offset: +02 = Kigali.
INSERT INTO reservations (table_id, customer_id, party_size, start_time, end_time, status) VALUES
    -- Table 2 (restaurant 1, 4 seats) is TAKEN 19:00-21:00 on 15 Nov
    (2, 1, 4, '2026-11-15 19:00+02', '2026-11-15 21:00+02', 'booked'),     -- id 1
    -- Table 3 (restaurant 1, 6 seats) is TAKEN 20:00-22:00 on 15 Nov
    (3, 2, 5, '2026-11-15 20:00+02', '2026-11-15 22:00+02', 'booked'),     -- id 2
    -- Cancelled booking that overlaps id 1: allowed, cancelled rows don't block
    (2, 3, 2, '2026-11-15 19:30+02', '2026-11-15 21:00+02', 'cancelled');  -- id 3

COMMIT;
