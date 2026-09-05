"""Gem store rotation tracker.

thatshaman.com's gem store tool (https://thatshaman.com/tools/gemstore/) is a
static page that fetches its own data from a plain JSON file - no scraping
needed, just a GET. Verified shape (2026-09):

    {
      "items": {"<item-guid>": {"name": str, "image": <hash>, "id": <gw2 item id or 0>, ...}, ...},
      "schedule": [{"item": "<item-guid>", "category": "<category-guid>", "start": iso8601, "end": iso8601}, ...]
    }

Icon URLs are built as https://services.staticwars.com/gw2/img/content/<image>_large.png
(that's the pattern thatshaman's own frontend uses).
"""
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger("gw2-ops-board.gemstore")

GEMSTORE_JSON_URL = "https://thatshaman.com/tools/gemstore/gemstore.json"
ICON_BASE = "https://services.staticwars.com/gw2/img/content/"

# Sentinel year thatshaman uses for "no end date" / permanently available entries.
_INDEFINITE_YEAR = 2050


def _wiki_url(name: str) -> str:
    return "https://wiki.guildwars2.com/wiki/" + name.replace(" ", "_")


async def fetch_gemstore_schedule() -> list[dict]:
    """Returns every schedule entry currently on sale/available, each as
    {"name", "icon", "wiki_url", "start", "end", "indefinite", "category_name"}."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(GEMSTORE_JSON_URL)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", {})
    categories = data.get("categories", {})
    now = datetime.now(timezone.utc)

    active = []
    for entry in data.get("schedule", []):
        item = items.get(entry.get("item"))
        if not item or not item.get("name"):
            continue
        try:
            start = datetime.fromisoformat(entry["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(entry["end"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue

        indefinite = end.year >= _INDEFINITE_YEAR
        if start > now or (not indefinite and end < now):
            continue  # not on sale yet, or already ended

        category = categories.get(entry.get("category"), {})
        active.append({
            "name": item["name"],
            "icon": ICON_BASE + item["image"] + "_large.png" if item.get("image") else None,
            "wiki_url": _wiki_url(item["name"]),
            "start": start.isoformat(),
            "end": None if indefinite else end.isoformat(),
            "indefinite": indefinite,
            "category_name": category.get("name", ""),
        })

    active.sort(key=lambda e: e["name"].lower())
    return active


def match_favorites(active_schedule: list[dict], favorites: list[str]) -> list[dict]:
    """Cross-references the currently-active gem store entries against a
    favorites list of item names (case-insensitive substring-free exact
    match on name), returning just the matches."""
    wanted = {name.lower() for name in favorites}
    return [entry for entry in active_schedule if entry["name"].lower() in wanted]


def filter_by_category(active_schedule: list[dict], category_name: str) -> list[dict]:
    """Everything currently active in one thatshaman category, independent
    of the personal favorites list - used for the "New Items" promotional
    rotation (their own featured-item showcase, distinct from the ~45-item
    "Seasonal Swap" bulk sales bundle)."""
    return [entry for entry in active_schedule if entry["category_name"] == category_name]
