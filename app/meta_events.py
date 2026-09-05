import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "meta_events.json"
_cached: dict | None = None

# Chronological order, each with a distinct hue (evenly spaced around the
# wheel) and its own expansion logo, used to color/label the category boxes
# on the timeline. HoT=green, PoF=red/orange per early feedback; the rest
# filled in around the wheel to stay visually distinct.
CATEGORY_ORDER = [
    ("Core Tyria", 180, "https://wiki.guildwars2.com/images/thumb/d/df/GW2Logo_new.png/96px-GW2Logo_new.png"),
    ("Heart of Thorns", 108, "https://wiki.guildwars2.com/images/thumb/5/52/HoT_Texture_Centered_Trans.png/96px-HoT_Texture_Centered_Trans.png"),
    ("Living World Season 3", 252, "https://wiki.guildwars2.com/images/thumb/c/ca/Living_World_Season_3_logo.png/96px-Living_World_Season_3_logo.png"),
    ("Path of Fire", 0, "https://wiki.guildwars2.com/images/thumb/0/0e/GW2-PoF_Texture_Centered_Trans.png/96px-GW2-PoF_Texture_Centered_Trans.png"),
    ("Living World Season 4", 36, "https://wiki.guildwars2.com/images/thumb/a/a1/Living_World_Season_4_logo.png/96px-Living_World_Season_4_logo.png"),
    ("Icebrood Saga", 216, "https://wiki.guildwars2.com/images/thumb/1/19/Living_World_Season_5_logo.png/96px-Living_World_Season_5_logo.png"),
    ("End of Dragons", 144, "https://wiki.guildwars2.com/images/thumb/c/cc/EoD_Texture_Trans.png/96px-EoD_Texture_Trans.png"),
    ("Secrets of the Obscure", 288, "https://wiki.guildwars2.com/images/thumb/4/44/Secrets_of_the_Obscure_logo.png/96px-Secrets_of_the_Obscure_logo.png"),
    ("Janthir Wilds", 72, "https://wiki.guildwars2.com/images/thumb/6/60/Janthir_Wilds_logo.png/96px-Janthir_Wilds_logo.png"),
    ("Visions of Eternity", 324, "https://wiki.guildwars2.com/images/thumb/c/cd/Visions_of_Eternity_logo.png/96px-Visions_of_Eternity_logo.png"),
]
WORLD_BOSS_HUE = 45  # gold, distinct from every category color
WORLD_BOSS_ICON = CATEGORY_ORDER[0][2]  # reuse the base GW2 logo


def load_meta_events() -> dict:
    """Static data (2-hour-cycle zone events, grouped by expansion), loaded
    once and cached - see the JSON's own "source"/"note" fields."""
    global _cached
    if _cached is None:
        _cached = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _cached


def zones_by_category() -> dict[str, list[dict]]:
    data = load_meta_events()
    grouped: dict[str, list[dict]] = {}
    for zone in data["zones"]:
        grouped.setdefault(zone["category"], []).append(zone)
    return grouped
