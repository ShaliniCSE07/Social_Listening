import os
from pymongo import MongoClient

_client: MongoClient | None = None


def get_db():
    global _client
    if _client is None:
        uri = os.environ.get("SOCL_MONGO_URI", "mongodb://localhost:27017")
        _client = MongoClient(uri)
    return _client["socl_db"]


def ensure_indexes():
    db = get_db()
    db.checkpoints.create_index(
        [("companyId", 1), ("platform", 1)], unique=True
    )
    db.records.create_index([("recordId", 1)], unique=True)
    db.records.create_index([("companyId", 1), ("platform", 1), ("platformItemId", 1), ("version", 1)])