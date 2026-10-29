"""Analytical queries: restaurant ranking per city and location search."""
from app.db import get_connection

RANK_BY_CITY_QUERY = """
    WITH restaurant_scores AS (
        -- One row per restaurant that has enough reviews
        SELECT r.id, r.name, r.city_id,
               AVG(v.rating) AS avg_rating,
               COUNT(*)      AS review_count
        FROM restaurants r
        JOIN reviews v ON v.restaurant_id = r.id
        GROUP BY r.id
        HAVING COUNT(*) >= %(min_reviews)s
    )
    SELECT c.name                   AS city,
           s.id                     AS restaurant_id,
           s.name                   AS restaurant,
           ROUND(s.avg_rating, 2)   AS avg_rating,
           s.review_count,
           -- Ranking restarts for every city; equal averages share a rank
           RANK() OVER (PARTITION BY s.city_id ORDER BY s.avg_rating DESC) AS city_rank
    FROM restaurant_scores s
    JOIN cities c ON c.id = s.city_id
    ORDER BY c.name, city_rank, s.name
"""

NEARBY_QUERY = """
    WITH search_point AS (
        -- ST_MakePoint takes LONGITUDE first, then LATITUDE
        SELECT ST_MakePoint(%(longitude)s, %(latitude)s)::geography AS point
    )
    SELECT r.id, r.name, c.name AS city,
           ROUND((ST_Distance(r.location, p.point) / 1000)::numeric, 2) AS distance_km
    FROM restaurants r
    JOIN cities c ON c.id = r.city_id
    CROSS JOIN search_point p
    -- ST_DWithin can use the GiST index on location; distance is in metres
    WHERE ST_DWithin(r.location, p.point, %(radius_m)s)
    ORDER BY distance_km, r.id
    LIMIT %(limit)s
"""


def rank_restaurants_by_city(min_reviews=1):
    """Every reviewed restaurant with its average rating and its rank inside its city."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(RANK_BY_CITY_QUERY, {"min_reviews": min_reviews})
            rows = cur.fetchall()

    return [
        {
            "city": city,
            "restaurant_id": restaurant_id,
            "restaurant": name,
            "avg_rating": float(avg_rating),
            "review_count": review_count,
            "city_rank": city_rank,
        }
        for city, restaurant_id, name, avg_rating, review_count, city_rank in rows
    ]


def find_restaurants_near(latitude, longitude, radius_km, limit=20):
    """Restaurants within radius_km of a point, closest first."""
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "radius_m": radius_km * 1000,
        "limit": limit,
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(NEARBY_QUERY, params)
            rows = cur.fetchall()

    return [
        {"restaurant_id": rid, "restaurant": name, "city": city, "distance_km": float(km)}
        for rid, name, city, km in rows
    ]


if __name__ == "__main__":
    # Manual demo against the current data
    for row in rank_restaurants_by_city():
        print(row)

    print("\nWithin 5 km of central Kigali:")
    for row in find_restaurants_near(latitude=-1.9441, longitude=30.0619, radius_km=5):
        print(row)
