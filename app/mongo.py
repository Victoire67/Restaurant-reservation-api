"""MongoDB client shared by the whole application."""
import os
import threading

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

load_dotenv()

_client = None
_client_lock = threading.Lock()


def get_mongo():
    """Create the MongoDB client on first use, then return the same client every time.

    MongoClient keeps its own connection pool, so one client can safely be
    shared between threads.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # another thread may have created it while we waited
                _client = MongoClient(
                    host=os.getenv("MONGO_HOST"),
                    port=int(os.getenv("MONGO_PORT", "27017")),
                    username=os.getenv("MONGO_USER"),
                    password=os.getenv("MONGO_PASSWORD"),
                )
                _create_indexes(_client)
    return _client


def get_feedback_collection():
    """The collection holding the long-form review text."""
    return get_mongo()[os.getenv("MONGO_DB", "restaurant_feedback")]["feedback"]


def _create_indexes(client):
    # "Latest reviews for restaurant X" is the main read; create_index is a no-op if it exists
    feedback = client[os.getenv("MONGO_DB", "restaurant_feedback")]["feedback"]
    feedback.create_index([("restaurant_id", ASCENDING), ("created_at", DESCENDING)])


if __name__ == "__main__":
    # Quick self-check: ping the server and count the feedback documents
    print("MongoDB works:", get_mongo().admin.command("ping"))
    print("Feedback documents:", get_feedback_collection().count_documents({}))
