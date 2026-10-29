"""Server-only MongoDB configuration; credentials never reach the browser."""

import atexit
import os
from functools import lru_cache
from pathlib import Path

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConfigurationError

load_dotenv(Path(__file__).with_name(".env"))


class StorageUnavailable(Exception):
    """A safe error that may be returned to a browser without exposing secrets."""


def uses_mongodb():
    mode = os.environ.get("QUESTION_STORAGE", "").strip().lower()
    if mode not in {"", "json", "mongodb"}:
        raise StorageUnavailable("QUESTION_STORAGE must be mongodb or json.")
    return mode == "mongodb" or (not mode and bool(os.environ.get("MONGODB_URI")))


@lru_cache(maxsize=1)
def get_question_collection():
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise StorageUnavailable("MongoDB is not configured. Set MONGODB_URI on the server.")
    # Atlas SRV connections use verified TLS. Do not disable certificate checking.
    options = {"tlsCAFile": certifi.where()} if uri.startswith("mongodb+srv://") else {}
    client = None
    try:
        client = MongoClient(
            uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
            socketTimeoutMS=10000, appname="JeoPartyOnline", **options,
        )
        database_name = os.environ.get("MONGODB_DATABASE", "").strip()
        database = client[database_name] if database_name else client.get_default_database("jeoparty")
        atexit.register(client.close)
        return database["question_sets"]
    except (ConfigurationError, ValueError):
        if client is not None:
            client.close()
        raise StorageUnavailable(
            "Cannot configure MongoDB. Check the connection URI and the server's DNS access."
        ) from None
