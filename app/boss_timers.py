import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "world_bosses.json"
_cached: dict | None = None


def load_world_boss_schedule() -> dict:
    """Static data, loaded once and cached - no network fetch needed, since
    this is a fixed, publicly documented UTC schedule (see the JSON's own
    "source"/"note" fields)."""
    global _cached
    if _cached is None:
        _cached = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _cached
