"""Store question sets in MongoDB, or JSON files for unconfigured local development.

Schema (matches the original tkinter game's questions.json):
    {
      "name": "Optional display name",
      "categories": [str, str, str, str, str, str],
      "questions": [
        {"category": "1", "question": str, "answer": str, "points": int},
        ...
      ],
      "password": "Optional creator password (plain text), never sent to browsers"
    }

The "category" field is 1-indexed into the categories array.
"""

import json
import re
from functools import lru_cache, wraps
from pathlib import Path

from pymongo.errors import DuplicateKeyError, PyMongoError

from database import StorageUnavailable, get_question_collection, uses_mongodb

QUESTIONS_DIR = Path(__file__).parent / "questions"


def _storage_errors(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PyMongoError:
            # Driver messages can contain connection details. Keep them server-private.
            raise StorageUnavailable(
                "Question storage is unavailable. Check MongoDB credentials and network access on the server."
            ) from None
    return wrapped


@lru_cache(maxsize=1)
def _mongo_collection():
    """Import existing JSON packs once per process without overwriting saved packs.

    MongoDB's unique _id makes imports repeatable across restarts and deploys.
    Failed imports are not cached and can be retried after fixing Atlas settings.
    """
    collection = get_question_collection()
    for path in sorted(QUESTIONS_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as source:
                data = json.load(source)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or len(data.get("categories", [])) < 6:
            continue
        payload = {
            "name": data.get("name") or path.stem,
            "categories": data["categories"][:6],
            "questions": data.get("questions", []),
        }
        collection.update_one({"_id": path.stem}, {"$setOnInsert": payload}, upsert=True)
    return collection


def slugify(name):
    """Turn a display name into a safe filename stem (lowercase, hyphens, ASCII)."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s or "set"


@_storage_errors
def save_set(name, categories, questions, password=""):
    """Persist a question set. Auto-suffixes on conflict, including concurrent saves.

    Returns the saved (filename_stem, display_name).
    """
    base = slugify(name)
    payload = {
        "name": name,
        "categories": list(categories),
        "questions": list(questions),
        "password": password,
    }
    if uses_mongodb():
        collection = _mongo_collection()
        stem = base
        n = 2
        while True:
            try:
                collection.insert_one({"_id": stem, **payload})
                return stem, name
            except DuplicateKeyError:
                stem = f"{base}-{n}"
                n += 1

    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    stem = base
    n = 2
    while (QUESTIONS_DIR / f"{stem}.json").exists():
        stem = f"{base}-{n}"
        n += 1

    _write_json(stem, payload)
    return stem, name


@_storage_errors
def list_sets():
    """Return question-set metadata only; answers are never included."""
    if uses_mongodb():
        return [
            {
                "filename": data["_id"],
                "name": data.get("name") or data["_id"],
                "categories": data.get("categories", [])[:6],
                "question_count": data.get("question_count", 0),
            }
            for data in _mongo_collection().aggregate([
                {"$match": {"deleted": {"$ne": True}}},
                {"$project": {"name": 1, "categories": 1,
                               "question_count": {"$size": {"$ifNull": ["$questions", []]}}}},
                {"$sort": {"_id": 1}},
            ])
        ]
    sets = []
    if not QUESTIONS_DIR.exists():
        return sets

    for path in sorted(QUESTIONS_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[question_loader] skipping {path.name}: {e}")
            continue

        categories = data.get("categories", [])
        if len(categories) < 6:
            print(f"[question_loader] skipping {path.name}: needs >=6 categories")
            continue

        sets.append({
            "filename": path.stem,
            "name": data.get("name") or path.stem,
            "categories": categories[:6],
            "question_count": len(data.get("questions", [])),
        })
    return sets


def _check_filename(filename):
    if not isinstance(filename, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", filename):
        raise FileNotFoundError(f"question set not found: {filename}")


def _read_set(filename):
    """Return the stored document for one set, or raise FileNotFoundError."""
    _check_filename(filename)
    if uses_mongodb():
        data = _mongo_collection().find_one({"_id": filename, "deleted": {"$ne": True}})
        if data is None:
            raise FileNotFoundError(f"question set not found: {filename}")
        return data
    path = QUESTIONS_DIR / f"{filename}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(filename, payload):
    path = QUESTIONS_DIR / f"{filename}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


@_storage_errors
def get_set(filename):
    """Return one full set for the editor: {"filename", "name", "categories", "questions"}."""
    data = _read_set(filename)
    return {
        "filename": filename,
        "name": data.get("name") or filename,
        "categories": data.get("categories", [])[:6],
        "questions": data.get("questions", []),
    }


@_storage_errors
def get_set_password(filename):
    """Return a set's creator password, or "" if it has none."""
    password = _read_set(filename).get("password")
    return password if isinstance(password, str) else ""


@_storage_errors
def update_set(filename, name, categories, questions, password=None):
    """Replace a set's name and contents in place. The filename stem never changes.

    password=None keeps the existing creator password.
    """
    existing = _read_set(filename)
    if password is None:
        password = existing.get("password") or ""
    payload = {"name": name, "categories": list(categories), "questions": list(questions),
               "password": password}
    if uses_mongodb():
        _mongo_collection().replace_one({"_id": filename}, payload)
    else:
        _write_json(filename, payload)
    return filename, name


@_storage_errors
def rename_set(filename, name):
    """Change only the display name. The filename stem never changes."""
    data = _read_set(filename)
    if uses_mongodb():
        _mongo_collection().update_one({"_id": filename}, {"$set": {"name": name}})
    else:
        data["name"] = name
        _write_json(filename, data)
    return filename, name


@_storage_errors
def delete_set(filename):
    """Remove a set. Raises FileNotFoundError if it does not exist."""
    _read_set(filename)
    if uses_mongodb():
        collection = _mongo_collection()
        if (QUESTIONS_DIR / f"{filename}.json").exists():
            # Bundled packs are re-imported on startup unless a tombstone holds their _id.
            collection.replace_one({"_id": filename}, {"deleted": True})
        else:
            collection.delete_one({"_id": filename})
        return
    (QUESTIONS_DIR / f"{filename}.json").unlink()


@_storage_errors
def load_set(filename):
    """Load and parse one question set by filename stem.

    Returns {"name", "categories", "questions_by_category"} or raises FileNotFoundError.
    """
    data = _read_set(filename)

    categories = data.get("categories", [])[:6]
    questions_by_category = {c: [] for c in categories}

    for q in data.get("questions", []):
        try:
            idx = int(q.get("category", 1)) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(categories):
            questions_by_category[categories[idx]].append({
                "question": q.get("question", ""),
                "answer": q.get("answer", ""),
                "points": int(q.get("points", 0)),
            })

    return {
        "name": data.get("name") or filename,
        "categories": categories,
        "questions_by_category": questions_by_category,
    }
