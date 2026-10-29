"""Reviews split across two databases.

PostgreSQL `reviews` keeps the structured part (who, where, rating), which is
what RANK() and averages need. MongoDB keeps the long-form text, which is
free-shaped and can be long. The Postgres row points to the Mongo document
through `mongo_feedback_id`.

The two databases cannot share one transaction, so submit_review() writes
Mongo first and, if the Postgres insert then fails, deletes the Mongo document
again (a compensating action). That way no review text is left orphaned.
"""
from datetime import datetime, timezone

from bson import ObjectId
from psycopg2 import Error as PostgresError

from app.db import get_connection
from app.mongo import get_feedback_collection


def submit_review(customer_id, restaurant_id, rating, title, body):
    """Save a review in both databases and return the Postgres review id."""
    if not 1 <= rating <= 5:
        raise ValueError("rating must be between 1 and 5")
    if not body or not body.strip():
        raise ValueError("review text must not be empty")

    # 1. Long-form text -> MongoDB
    feedback = get_feedback_collection()
    mongo_id = feedback.insert_one({
        "restaurant_id": restaurant_id,
        "customer_id": customer_id,
        "title": title,
        "body": body.strip(),
        "created_at": datetime.now(timezone.utc),
    }).inserted_id

    # 2. Structured part -> PostgreSQL, linked to the Mongo document
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reviews (restaurant_id, customer_id, rating, mongo_feedback_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (restaurant_id, customer_id, rating, str(mongo_id)),
                )
                return cur.fetchone()[0]
    except PostgresError:
        # e.g. unknown customer/restaurant (foreign key): undo step 1, then report the error
        feedback.delete_one({"_id": mongo_id})
        raise


def get_review(review_id):
    """One review with its rating (Postgres) and text (MongoDB), or None."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, restaurant_id, customer_id, rating, mongo_feedback_id, created_at
                FROM reviews
                WHERE id = %s
                """,
                (review_id,),
            )
            row = cur.fetchone()

    if row is None:
        return None

    review = _row_to_review(row)
    text = _load_texts([row[4]]).get(row[4], {})
    review["title"] = text.get("title")
    review["body"] = text.get("body")
    return review


def get_restaurant_reviews(restaurant_id, limit=20):
    """Latest reviews of one restaurant, each with its text, newest first."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, restaurant_id, customer_id, rating, mongo_feedback_id, created_at
                FROM reviews
                WHERE restaurant_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (restaurant_id, limit),
            )
            rows = cur.fetchall()

    # One Mongo query for all texts instead of one query per review
    texts = _load_texts([row[4] for row in rows])

    reviews = []
    for row in rows:
        review = _row_to_review(row)
        text = texts.get(row[4], {})
        review["title"] = text.get("title")
        review["body"] = text.get("body")
        reviews.append(review)
    return reviews


# --- Helpers -----------------------------------------------------------------

def _row_to_review(row):
    review_id, restaurant_id, customer_id, rating, _mongo_id, created_at = row
    return {
        "review_id": review_id,
        "restaurant_id": restaurant_id,
        "customer_id": customer_id,
        "rating": rating,
        "created_at": created_at,
    }


def _load_texts(mongo_ids):
    """Fetch Mongo documents by id; returns {mongo_id_as_str: document}."""
    ids = [ObjectId(m) for m in mongo_ids if m]
    if not ids:
        return {}
    documents = get_feedback_collection().find({"_id": {"$in": ids}})
    return {str(doc["_id"]): doc for doc in documents}


if __name__ == "__main__":
    # Manual demo against the seed data
    new_id = submit_review(
        customer_id=1,
        restaurant_id=1,
        rating=5,
        title="Best brochettes in town",
        body="Warm staff, quick service and the goat brochettes were perfectly grilled.",
    )
    print("Saved review id:", new_id)
    print(get_review(new_id))
