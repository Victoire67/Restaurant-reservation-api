"""Redis client shared by the whole application."""
import os
import threading

import redis
from dotenv import load_dotenv

load_dotenv()

_client = None
_client_lock = threading.Lock()


def get_redis():
    """Create the Redis client on first use, then return the same client every time.

    redis-py keeps its own connection pool inside the client, so one client
    can safely be shared between threads.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # another thread may have created it while we waited
                _client = redis.Redis(
                    host=os.getenv("REDIS_HOST"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    decode_responses=True,  # return str instead of bytes
                )
    return _client


if __name__ == "__main__":
    # Quick self-check: write a key, read it back, delete it
    r = get_redis()
    r.set("selfcheck", "ok", ex=10)
    print("Redis works:", r.get("selfcheck"))
    r.delete("selfcheck")
