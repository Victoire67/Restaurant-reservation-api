"""Tests for the ranking and location queries (run against the seed data)."""
from pathlib import Path

import pytest

from app.analytics import find_restaurants_near, rank_restaurants_by_city
from app.db import close_pool, get_connection

SEED_FILE = Path(__file__).resolve().parent.parent / "sql" / "seed.sql"

# Seed coordinates of restaurant 1 (Ikirezi Bistro, Kigali) and 4 (Le Petit Jardin, Paris)
KIGALI_BISTRO = {"latitude": -1.9441, "longitude": 30.0619}
PARIS_JARDIN = {"latitude": 48.8566, "longitude": 2.3522}


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


def add_ratings(restaurant_id, *ratings):
    """Insert ratings directly in Postgres (the Mongo text is not needed for ranking)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for i, rating in enumerate(ratings):
                customer_id = i % 5 + 1
                cur.execute(
                    "INSERT INTO reviews (restaurant_id, customer_id, rating) VALUES (%s, %s, %s)",
                    (restaurant_id, customer_id, rating),
                )


def ranks_by_id(rows):
    return {row["restaurant_id"]: row["city_rank"] for row in rows}


# --- RANK() per city ---------------------------------------------------------

def test_restaurants_are_ranked_by_average_inside_their_city():
    add_ratings(1, 5, 4)      # Kigali, avg 4.5
    add_ratings(2, 5, 5)      # Kigali, avg 5.0
    add_ratings(3, 3)         # Nairobi, avg 3.0

    ranks = ranks_by_id(rank_restaurants_by_city())

    assert ranks == {2: 1, 1: 2, 3: 1}  # Nairobi's only restaurant is #1 in its own city


def test_equal_averages_share_a_rank():
    add_ratings(1, 4, 4)
    add_ratings(2, 5, 3)      # also avg 4.0

    ranks = ranks_by_id(rank_restaurants_by_city())

    assert ranks[1] == ranks[2] == 1


def test_average_and_count_are_reported():
    add_ratings(1, 5, 4, 4)

    row = rank_restaurants_by_city()[0]

    assert row["avg_rating"] == 4.33
    assert row["review_count"] == 3


def test_restaurants_without_enough_reviews_are_left_out():
    add_ratings(1, 5, 5)
    add_ratings(2, 4)

    ids = [row["restaurant_id"] for row in rank_restaurants_by_city(min_reviews=2)]

    assert ids == [1]


# --- Location search (GiST) ----------------------------------------------------

def test_nearby_restaurants_are_sorted_by_distance():
    results = find_restaurants_near(**KIGALI_BISTRO, radius_km=5)

    assert [r["restaurant_id"] for r in results] == [1, 2]
    assert results[0]["distance_km"] == 0
    assert 2 < results[1]["distance_km"] < 5


def test_small_radius_excludes_farther_restaurants():
    results = find_restaurants_near(**KIGALI_BISTRO, radius_km=1)

    assert [r["restaurant_id"] for r in results] == [1]


def test_search_in_another_city():
    results = find_restaurants_near(**PARIS_JARDIN, radius_km=10)

    assert [r["city"] for r in results] == ["Paris"]


def test_radius_must_be_positive():
    with pytest.raises(ValueError):
        find_restaurants_near(**KIGALI_BISTRO, radius_km=0)
