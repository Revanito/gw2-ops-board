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


async def fetch_gemstore_data() -> dict:
    """Returns {"active": [...], "catalog": {name_lower: {...}}}.

    "active" is every schedule entry currently on sale/available, each as
    {"name", "icon", "wiki_url", "start", "end", "indefinite", "category_name"}.

    "catalog" is base info (name/icon/wiki_url) for *every* item thatshaman
    tracks, active or not - needed so the favorites list can still show an
    item (greyed out) when it isn't currently on sale, instead of the item
    just disappearing from the page entirely."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(GEMSTORE_JSON_URL)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", {})
    categories = data.get("categories", {})
    now = datetime.now(timezone.utc)

    catalog = {}
    for item in items.values():
        name = item.get("name")
        if not name:
            continue
        catalog[name.lower()] = {
            "name": name,
            "icon": ICON_BASE + item["image"] + "_large.png" if item.get("image") else None,
            "wiki_url": _wiki_url(name),
        }

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
    return {"active": active, "catalog": catalog}


def build_favorites_view(data: dict, favorites: list[str]) -> list[dict]:
    """One entry per name in favorites.json, in that order - always shown,
    not just when on sale. An entry currently on sale carries the live
    schedule info and "available": True; one that isn't still shows its
    name/icon (from the full catalog) with "available": False so the
    template can grey it out instead of hiding it. A name thatshaman
    doesn't track at all (typo, or genuinely never listed) still gets a
    bare entry rather than silently vanishing."""
    active_by_name = {e["name"].lower(): e for e in data["active"]}
    catalog = data["catalog"]

    result = []
    for name in favorites:
        key = name.lower()
        active_entry = active_by_name.get(key)
        if active_entry:
            result.append({**active_entry, "available": True})
            continue
        base = catalog.get(key, {"name": name, "icon": None, "wiki_url": _wiki_url(name)})
        result.append({**base, "available": False, "price": None, "end": None, "indefinite": False})
    return result


def filter_by_category(active_schedule: list[dict], category_name: str) -> list[dict]:
    """Everything currently active in one thatshaman category, independent
    of the personal favorites list - used for the "New Items" promotional
    rotation (their own featured-item showcase, distinct from the ~45-item
    "Seasonal Swap" bulk sales bundle)."""
    return [entry for entry in active_schedule if entry["category_name"] == category_name]
