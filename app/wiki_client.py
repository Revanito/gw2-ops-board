"""Best-effort gem price + icon lookup via the wiki's MediaWiki API.

The official GW2 API has no gem store catalog endpoint (thatshaman's tracker
doesn't carry price either - see gemstore_client.py's docstring), so gem
prices only exist as human-maintained text on each item's wiki page, in a
"Sold by" table like:

    | Vendor              | Area | Zone | Cost      |
    | Gem Store            |      |      | 700 [Gem] |

Verified against https://wiki.guildwars2.com/wiki/Wandering_Weapon_Master_Outfit
(2026-09): rendered as <table class="npc sortable table"> with a row whose
first cell links to "Gem Store" and whose last cell holds the price text.
Not every item page has this table (contents-only items, discontinued
vendors, etc.) - callers should treat a None return as "no price available,
link to the wiki page instead" rather than an error.
"""
import logging
import re

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("gw2-ops-board.wiki")

WIKI_API = "https://wiki.guildwars2.com/api.php"
WIKI_UA = "gw2-ops-board/1.0 (personal guild tool; contact via github.com/Revanito)"


async def fetch_gem_price(item_name: str) -> str | None:
    """Returns a display string like "700 Gems" or None if not found."""
    page = item_name.replace(" ", "_")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                WIKI_API,
                params={"action": "parse", "page": page, "format": "json", "prop": "text"},
                headers={"User-Agent": WIKI_UA},
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPError:
        log.exception("wiki fetch failed for %s", item_name)
        return None

    if "error" in payload:
        return None

    html = payload.get("parse", {}).get("text", {}).get("*", "")
    soup = BeautifulSoup(html, "html.parser")

    for table in soup.select("table.npc"):
        for row in table.select("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            if "gem store" in cells[0].get_text(strip=True).lower():
                price_cell = cells[-1]
                amount = price_cell.get_text(" ", strip=True)
                amount = re.sub(r"\s+", " ", amount).strip()
                if not amount:
                    continue
                # The currency itself is conveyed only by an icon (e.g. a link to
                # "/wiki/Gem"), not text, so it has to be read off the icon link.
                currency_link = price_cell.select_one("a[title]")
                unit = currency_link["title"] if currency_link else "Gems"
                return f"{amount} {unit}"
    return None
