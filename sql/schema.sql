-- =====================================================================
-- Restaurant Reservation & Review System - PostgreSQL schema (3NF)
-- Re-runnable: drops everything first, then recreates it.
-- =====================================================================

-- Drop in reverse dependency order (children before parents)
DROP TABLE IF EXISTS reviews CASCADE;
DROP TABLE IF EXISTS reservations CASCADE;
DROP TABLE IF EXISTS restaurant_tables CASCADE;
DROP TABLE IF EXISTS restaurants CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS cities CASCADE;



-- PostGIS: GEOGRAPHY type + distance functions (location search with GiST)
CREATE EXTENSION IF NOT EXISTS postgis;

-- btree_gist: lets a GiST index compare plain integers (needed by the
-- anti-double-booking exclusion constraint on reservations)
CREATE EXTENSION IF NOT EXISTS btree_gist;


-- ---------------------------------------------------------------------
-- cities: one row per city, so "rank per city" groups reliably
-- ---------------------------------------------------------------------
CREATE TABLE cities (
    id      INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name    TEXT NOT NULL,
    country TEXT NOT NULL,
    CONSTRAINT uq_cities_name_country UNIQUE (name, country)
);

-- ---------------------------------------------------------------------
-- customers: shared across all restaurants on the platform
-- ---------------------------------------------------------------------
CREATE TABLE customers (
    id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name  TEXT NOT NULL,
    email      TEXT NOT NULL,
    phone      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_customers_email UNIQUE (email)
);


-- ---------------------------------------------------------------------
-- restaurants: menu and opening hours are semi-structured -> JSONB
-- ---------------------------------------------------------------------
CREATE TABLE restaurants (
    id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city_id       INT NOT NULL,
    name          TEXT NOT NULL,
    address       TEXT NOT NULL,
    phone         TEXT,
    location      GEOGRAPHY(POINT, 4326) NOT NULL,
    menu          JSONB NOT NULL DEFAULT '{}'::jsonb,
    opening_hours JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_restaurants_city FOREIGN KEY (city_id) REFERENCES cities (id)
);


-- ---------------------------------------------------------------------
-- restaurant_tables: the physical tables inside each restaurant
-- ---------------------------------------------------------------------
CREATE TABLE restaurant_tables (
    id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    restaurant_id INT NOT NULL,
    table_number  INT NOT NULL,
    capacity      INT NOT NULL,
    CONSTRAINT fk_tables_restaurant FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
    CONSTRAINT uq_tables_restaurant_number UNIQUE (restaurant_id, table_number),
    CONSTRAINT chk_tables_capacity CHECK (capacity > 0)
);

-- ---------------------------------------------------------------------
-- reservations: no restaurant_id here (3NF) - it is derived via table_id
-- ---------------------------------------------------------------------
CREATE TABLE reservations (
    id          INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_id    INT NOT NULL,
    customer_id INT NOT NULL,
    party_size  INT NOT NULL,
    start_time  TIMESTAMPTZ NOT NULL,
    end_time    TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'booked',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_reservations_table FOREIGN KEY (table_id) REFERENCES restaurant_tables (id),
    CONSTRAINT fk_reservations_customer FOREIGN KEY (customer_id) REFERENCES customers (id),
    CONSTRAINT chk_reservations_party_size CHECK (party_size > 0),
    CONSTRAINT chk_reservations_time_order CHECK (end_time > start_time),
    CONSTRAINT chk_reservations_status CHECK (status IN ('booked', 'cancelled', 'completed')),
    -- Safety net: two 'booked' reservations on the same table can never overlap
    CONSTRAINT excl_reservations_no_overlap EXCLUDE USING gist (
        table_id WITH =,
        tstzrange(start_time, end_time, '[)') WITH &&
    ) WHERE (status = 'booked')
);


-- ---------------------------------------------------------------------
-- reviews: structured rating lives here (used by RANK());
-- the long-form text lives in MongoDB, linked by mongo_feedback_id
-- ---------------------------------------------------------------------
CREATE TABLE reviews (
    id                INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    restaurant_id     INT NOT NULL,
    customer_id       INT NOT NULL,
    rating            SMALLINT NOT NULL,
    mongo_feedback_id TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_reviews_restaurant FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
    CONSTRAINT fk_reviews_customer FOREIGN KEY (customer_id) REFERENCES customers (id),
    CONSTRAINT chk_reviews_rating CHECK (rating BETWEEN 1 AND 5)
);
