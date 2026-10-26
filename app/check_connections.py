"""Quick sanity check that Python can reach PostgreSQL, Redis and MongoDB."""
import os

import psycopg2
import redis
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# PostgreSQL
conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    dbname=os.getenv("POSTGRES_DB"),
)
with conn.cursor() as cur:
    cur.execute("SELECT version();")
    print("PostgreSQL:", cur.fetchone()[0][:40])
conn.close()

# Redis
r = redis.Redis(host=os.getenv("REDIS_HOST"), port=int(os.getenv("REDIS_PORT")))
print("Redis:", r.ping())

# MongoDB
mongo = MongoClient(
    host=os.getenv("MONGO_HOST"),
    port=int(os.getenv("MONGO_PORT")),
    username=os.getenv("MONGO_USER"),
    password=os.getenv("MONGO_PASSWORD"),
)
print("MongoDB:", mongo.admin.command("ping"))
