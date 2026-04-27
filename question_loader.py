"""Discover and load question sets from the questions/ folder.

Schema (matches the original tkinter game's questions.json):
    {
      "name": "Optional display name",
      "categories": [str, str, str, str, str, str],
      "questions": [
        {"category": "1", "question": str, "answer": str, "points": int},
        ...
      ]
    }

The "category" field is 1-indexed into the categories array.
"""

import json
import os
from pathlib import Path

QUESTIONS_DIR = Path(__file__).parent / "questions"


def list_sets():
    """Return metadata for every loadable JSON file in questions/."""
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


def load_set(filename):
    """Load and parse one question set by filename stem.

    Returns {"name", "categories", "questions_by_category"} or raises FileNotFoundError.
    """
    path = QUESTIONS_DIR / f"{filename}.json"
    if not path.exists():
        raise FileNotFoundError(f"question set not found: {filename}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

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
