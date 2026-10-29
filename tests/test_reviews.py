"""Tests for reviews split across PostgreSQL (rating) and MongoDB (text)."""
from pathlib import Path

import pytest
from bson import ObjectId
from psycopg2 import errors

from app.db import close_pool, get_connection
from app.mongo import get_feedback_collection
from app.reviews import get_restaurant_reviews, get_review, submit_review

SEED_FILE = Path(__file__).resolve().parent.parent / "sql" / "seed.sql"


@pytest.fixture(autouse=True)
def fresh_data():
    """Reset Postgres to the seed data and empty the feedback collection before every test."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SEED_FILE.read_text(encoding="utf-8"))
    get_feedback_collection().delete_many({})


@pytest.fixture(scope="session", autouse=True)
def pool_cleanup():
    """Close the connection pool once all tests have finished."""
    yield
    close_pool()


def postgres_review_count():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM reviews")
            return cur.fetchone()[0]


def mongo_feedback_count():
    return get_feedback_collection().count_documents({})


# --- Normal behaviour -------------------------------------------------------

def test_review_is_saved_in_both_databases():
    review_id = submit_review(1, 1, 5, "Great", "Lovely food and friendly staff.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rating, mongo_feedback_id FROM reviews WHERE id = %s", (review_id,))
            rating, mongo_id = cur.fetchone()

    assert rating == 5
    document = get_feedback_collection().find_one({"_id": ObjectId(mongo_id)})
    assert document["body"] == "Lovely food and friendly staff."


def test_get_review_combines_rating_and_text():
    review_id = submit_review(2, 1, 4, "Good", "Tasty bean stew.")

    review = get_review(review_id)

    assert review["rating"] == 4
    assert review["title"] == "Good"
    assert review["body"] == "Tasty bean stew."


def test_restaurant_reviews_are_newest_first_and_only_for_that_restaurant():
    first = submit_review(1, 1, 3, "Ok", "Decent.")
    second = submit_review(2, 1, 5, "Superb", "Came back twice.")
    submit_review(3, 2, 4, "Other place", "Not restaurant 1.")

    reviews = get_restaurant_reviews(1)

    assert [r["review_id"] for r in reviews] == [second, first]
    assert [r["body"] for r in reviews] == ["Came back twice.", "Decent."]


def test_unknown_review_returns_none():
    assert get_review(999) is None


# --- Refusals ---------------------------------------------------------------

@pytest.mark.parametrize("rating", [0, 6])
def test_rating_out_of_range_is_refused(rating):
    with pytest.raises(ValueError):
        submit_review(1, 1, rating, "Bad rating", "Some text.")


def test_empty_text_is_refused():
    with pytest.raises(ValueError):
        submit_review(1, 1, 4, "No text", "   ")


# --- Consistency between the two databases: the key test ---------------------

def test_failed_postgres_insert_leaves_no_orphan_text_in_mongo():
    # Restaurant 999 does not exist -> foreign key violation in Postgres
    with pytest.raises(errors.ForeignKeyViolation):
        submit_review(1, 999, 4, "Ghost", "This restaurant does not exist.")

    assert postgres_review_count() == 0
    assert mongo_feedback_count() == 0
