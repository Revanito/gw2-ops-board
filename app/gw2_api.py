"""Thin wrapper around the official Guild Wars 2 API (api.guildwars2.com).

Endpoints marked (auth) require the caller's own API key; everything else is
public. The API is read-only end to end - there is no endpoint that can move
items, spend currency, or otherwise act on an account, so a leaked read key
can only expose information, never let someone act on the account.
"""
import asyncio
import logging
import time
from urllib.parse import quote

import httpx

log = logging.getLogger("gw2-ops-board.gw2_api")

BASE = "https://api.guildwars2.com/v2"
REQUIRED_SCOPES = {"account", "wallet", "progression", "unlocks", "characters", "builds", "inventories"}

_client = httpx.AsyncClient(base_url=BASE, timeout=20)

# Small in-process TTL cache for public reference data that barely ever
# changes (currency names/icons, Wizard's Vault objective catalog).
_ref_cache: dict[str, tuple[float, object]] = {}
_REF_TTL_SECONDS = 3600


async def _get_ref(path: str, ttl: int = _REF_TTL_SECONDS):
    cached = _ref_cache.get(path)
    now = time.time()
    if cached and now - cached[0] < ttl:
        return cached[1]
    resp = await _client.get(path)
    resp.raise_for_status()
    data = resp.json()
    _ref_cache[path] = (now, data)
    return data


def _auth_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


async def validate_token(api_key: str) -> dict:
    """Returns {"ok": True, "missing_scopes": [...]} or {"ok": False, "error": "..."}."""
    try:
        resp = await _client.get("/tokeninfo", headers=_auth_headers(api_key))
    except httpx.RequestError as e:
        return {"ok": False, "error": f"couldn't reach the GW2 API ({e})"}

    if resp.status_code == 401:
        return {"ok": False, "error": "invalid API key"}
    resp.raise_for_status()

    permissions = set(resp.json().get("permissions", []))
    missing = REQUIRED_SCOPES - permissions
    return {"ok": True, "missing_scopes": sorted(missing)}


async def fetch_account(api_key: str) -> dict:
    resp = await _client.get("/account", headers=_auth_headers(api_key))
    resp.raise_for_status()
    return resp.json()


async def fetch_wallet(api_key: str) -> list[dict]:
    """Returns [{"id", "name", "icon", "value"}, ...] - account balance per
    currency, enriched with the (cached, public) currency catalog."""
    resp = await _client.get("/account/wallet", headers=_auth_headers(api_key))
    resp.raise_for_status()
    balances = {c["id"]: c["value"] for c in resp.json()}
    if not balances:
        return []

    currencies = await _get_ref(f"/currencies?ids={','.join(map(str, balances))}")
    by_id = {c["id"]: c for c in currencies}

    wallet = []
    for currency_id, value in balances.items():
        info = by_id.get(currency_id, {})
        wallet.append({
            "id": currency_id,
            "name": info.get("name", f"Currency {currency_id}"),
            "icon": info.get("icon"),
            "value": value,
        })
    wallet.sort(key=lambda c: by_id.get(c["id"], {}).get("order", 999))
    return wallet


async def fetch_wizards_vault_daily(api_key: str) -> dict | None:
    """Today's Wizard's Vault objectives and this account's progress on
    them. Returns None if the account has no data yet (e.g. brand new)."""
    resp = await _client.get("/account/wizardsvault/daily", headers=_auth_headers(api_key))
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    progress = resp.json()
    objective_progress = progress.get("objectives", progress if isinstance(progress, list) else [])
    ids = [o["id"] for o in objective_progress if "id" in o]
    if not ids:
        return {"meta_progress_current": progress.get("meta_progress_current"),
                "meta_progress_complete": progress.get("meta_progress_complete"), "objectives": []}

    catalog = await _get_ref(f"/wizardsvault/objectives?ids={','.join(map(str, ids))}")
    by_id = {o["id"]: o for o in catalog}

    objectives = []
    for o in objective_progress:
        info = by_id.get(o.get("id"), {})
        objectives.append({
            "title": info.get("title", f"Objective {o.get('id')}"),
            "track": info.get("track", ""),
            "acclaim": info.get("acclaim", 0),
            "progress_current": o.get("progress_current", 0),
            "progress_complete": o.get("progress_complete", 1),
            "claimed": o.get("claimed", False),
            "done": o.get("progress_current", 0) >= o.get("progress_complete", 1),
        })

    return {
        "meta_progress_current": progress.get("meta_progress_current"),
        "meta_progress_complete": progress.get("meta_progress_complete"),
        "objectives": objectives,
    }


async def _fetch_character_detail(name: str, api_key: str) -> tuple[dict, int | None, list[dict]] | None:
    """Character names routinely contain spaces/punctuation ("Ternowned
    Bladesworn"), so the name has to be percent-encoded before it can go into
    a URL path - passing it in raw silently breaks the request for most
    real accounts. The three per-character calls are independent, so they're
    issued concurrently rather than one after another.

    Returns None if this one character's data couldn't be made sense of, so
    the caller can skip it and still show everyone else - the GW2 API has
    turned out to occasionally return unexpected shapes here (a 403 on
    /specializations for keys missing "builds", and separately a bare string
    instead of a list from /crafting for at least one real character), and a
    single character's bad response shouldn't take down the whole list."""
    encoded = quote(name, safe="")
    headers = _auth_headers(api_key)
    try:
        core_resp, spec_resp, crafting_resp = await asyncio.gather(
            _client.get(f"/characters/{encoded}/core", headers=headers),
            _client.get(f"/characters/{encoded}/specializations", headers=headers),
            _client.get(f"/characters/{encoded}/crafting", headers=headers),
        )
        core_resp.raise_for_status()

        # /specializations needs the separate "builds" permission scope (not
        # covered by "characters", which only gates core/crafting/equipment/
        # inventory) - a key missing it gets a 403 here specifically.
        #
        # The response shape is inconsistently documented - some sources say
        # {"pve": [...], ...} flat, others say it's nested under a
        # "specializations" wrapper key. Handling both rather than betting on
        # one, since live testing showed 200 responses producing no data
        # under the flat assumption.
        pve_specs = []
        if spec_resp.status_code == 200:
            spec_json = spec_resp.json()
            if isinstance(spec_json, dict):
                specs_block = spec_json.get("specializations", spec_json)
                if isinstance(specs_block, dict):
                    pve_specs = specs_block.get("pve", []) or []
        # The 3rd PvE specialization slot is conventionally the elite spec.
        elite_id = None
        if len(pve_specs) > 2 and isinstance(pve_specs[2], dict):
            elite_id = pve_specs[2].get("id")

        # The API always returns all 9 disciplines per character, most at
        # rating 0/inactive if never trained. Shown here is every discipline
        # with any actual progress, not just the 2 a character currently has
        # equipped ("active") - trained-but-parked disciplines still count
        # as "a job this character knows" for display purposes.
        #
        # Response is wrapped as {"crafting": [...]}, not a bare list - the
        # same "wrapped under the endpoint's own name" shape as
        # /specializations above. This is also what caused the original
        # crash: iterating a dict directly yields its *keys* (strings), not
        # its values, hence 'str' object has no attribute 'get'.
        crafting = []
        if crafting_resp.status_code == 200:
            crafting_json = crafting_resp.json()
            crafting_list = crafting_json.get("crafting", crafting_json) if isinstance(crafting_json, dict) else crafting_json
            if isinstance(crafting_list, list):
                crafting = [d for d in crafting_list if isinstance(d, dict) and d.get("rating", 0) > 0]

        return core_resp.json(), elite_id, crafting
    except Exception:
        log.exception("couldn't fetch details for character %r", name)
        return None


async def fetch_characters(api_key: str) -> list[dict]:
    """One row per character: name, race, profession (Guardian, Necromancer,
    ...), level, current PvE elite specialization (if any is equipped), and
    active crafting disciplines (Armorsmith, Artificer, ... - a separate,
    unrelated concept from "profession" in GW2's own terminology, hence the
    dedicated /crafting endpoint below). All characters are fetched
    concurrently (three small calls each) rather than one at a time, so an
    account with a dozen+ characters doesn't turn the dashboard into a
    multi-second sequential wait."""
    resp = await _client.get("/characters", headers=_auth_headers(api_key))
    resp.raise_for_status()
    names = resp.json()
    if not names:
        return []

    raw_results = await asyncio.gather(*(_fetch_character_detail(name, api_key) for name in names))
    results = [r for r in raw_results if r is not None]

    elite_ids = sorted({elite_id for _, elite_id, _ in results if elite_id})
    spec_catalog = {}
    if elite_ids:
        data = await _get_ref(f"/specializations?ids={','.join(map(str, elite_ids))}", ttl=86400)
        spec_catalog = {s["id"]: s for s in data}

    characters = []
    for core, elite_id, crafting in results:
        spec_info = spec_catalog.get(elite_id)
        characters.append({
            "name": core["name"],
            "race": core.get("race", ""),
            "profession": core.get("profession", ""),
            "level": core.get("level", 0),
            "specialization": spec_info["name"] if spec_info else None,
            "specialization_icon": spec_info.get("icon") if spec_info else None,
            "crafting": [
                {"discipline": d["discipline"], "rating": d["rating"]} for d in crafting
            ],
        })
    characters.sort(key=lambda c: c["level"], reverse=True)
    return characters


async def fetch_materials(api_key: str) -> list[dict]:
    """Material Storage contents, grouped and ordered the same way the
    in-game Material Storage tab is (category order, then each category's
    own canonical item order). Needs the "inventories" scope - separate from
    "characters", same story as the "builds" scope for specializations.

    The API always returns every material the game knows about, most with
    count 0 (an account that's never held a given material still gets an
    entry for it) - those are filtered out here rather than shown as a wall
    of zeroes."""
    resp = await _client.get("/account/materials", headers=_auth_headers(api_key))
    resp.raise_for_status()
    held = {m["id"]: m["count"] for m in resp.json() if m.get("count", 0) > 0}
    if not held:
        return []

    # The GW2 API caps bulk ids= requests at 200 - a veteran account can
    # easily hold 200+ distinct materials, so this can't be a single call.
    ids = list(held)
    items: dict[int, dict] = {}
    for i in range(0, len(ids), 200):
        items.update(await fetch_items(ids[i:i + 200]))
    categories = await _get_ref("/materials?ids=all", ttl=86400)

    result = []
    for cat in sorted(categories, key=lambda c: c["order"]):
        item_order = {iid: i for i, iid in enumerate(cat["items"])}
        cat_items = []
        for item_id in cat["items"]:
            if item_id not in held:
                continue
            info = items.get(item_id, {})
            cat_items.append({
                "id": item_id,
                "name": info.get("name", f"Item {item_id}"),
                "icon": info.get("icon"),
                "count": held[item_id],
            })
        if cat_items:
            cat_items.sort(key=lambda i: item_order[i["id"]])
            result.append({"category": cat["name"], "materials": cat_items})

    return result


# In-process cache of the whole achievement catalog (id/name/top-tier
# count for every achievement in the game, ~8200 of them) - needed to
# resolve a typed achievement name to an id for the to-do list's optional
# achievement tracking. There's no official name-search endpoint, so this
# fetches the full catalog once (~42 chunked calls, done concurrently) and
# caches it long-term, since the catalog itself changes rarely (new content
# patches only). Loading it inline during a live request (the first time
# someone linked an achievement) caused a real nginx 504 - warm_achievement_
# cache() below is called once at app startup instead, so a user request
# never has to pay for this.
_achievement_cache: dict | None = None
_achievement_cache_loaded_at = 0.0
_achievement_cache_lock = asyncio.Lock()
_ACHIEVEMENT_CACHE_TTL = 86400


async def _load_achievement_cache() -> dict:
    global _achievement_cache, _achievement_cache_loaded_at
    now = time.time()
    if _achievement_cache is not None and now - _achievement_cache_loaded_at < _ACHIEVEMENT_CACHE_TTL:
        return _achievement_cache

    async with _achievement_cache_lock:
        # Another caller may have just finished loading it while this one
        # was waiting on the lock - re-check before fetching again.
        now = time.time()
        if _achievement_cache is not None and now - _achievement_cache_loaded_at < _ACHIEVEMENT_CACHE_TTL:
            return _achievement_cache

        ids_resp = await _client.get("/achievements")
        ids_resp.raise_for_status()
        all_ids = ids_resp.json()

        chunks = [all_ids[i:i + 200] for i in range(0, len(all_ids), 200)]
        responses = await asyncio.gather(
            *(_client.get(f"/achievements?ids={','.join(map(str, chunk))}") for chunk in chunks)
        )

        by_name: dict[str, dict] = {}
        by_id: dict[int, dict] = {}
        for resp in responses:
            resp.raise_for_status()
            for a in resp.json():
                name = a.get("name")
                if not name:
                    continue
                tiers = a.get("tiers") or []
                entry = {"id": a["id"], "name": name, "max": tiers[-1]["count"] if tiers else None}
                by_name[name.lower()] = entry
                by_id[a["id"]] = entry

        _achievement_cache = {"by_name": by_name, "by_id": by_id}
        _achievement_cache_loaded_at = time.time()
        return _achievement_cache


async def warm_achievement_cache() -> None:
    """Fire-and-forget at app startup - see the module comment above."""
    await _load_achievement_cache()


async def search_achievement(name: str) -> dict | None:
    """Case-insensitive exact-name lookup against the full achievement
    catalog. Returns {"id", "name", "max"} or None if nothing matches -
    there's no fuzzy/partial search here, the name has to match exactly
    (as it appears in-game) since the alternative is silently linking the
    wrong achievement."""
    cache = await _load_achievement_cache()
    return cache["by_name"].get(name.strip().lower())


async def fetch_achievement_progress(api_key: str, achievement_id: int) -> dict | None:
    """Live current/max/done for one achievement linked from the to-do
    list. An achievement with zero progress often has no entry at all in
    /account/achievements (rather than an entry showing 0), so "max" falls
    back to the achievement's own top-tier threshold from the catalog
    whenever the account has no progress entry yet."""
    resp = await _client.get(f"/account/achievements?ids={achievement_id}", headers=_auth_headers(api_key))
    resp.raise_for_status()
    rows = resp.json()
    entry = rows[0] if rows else {}

    cache = await _load_achievement_cache()
    cat_entry = cache["by_id"].get(achievement_id)
    if cat_entry is None:
        return None

    return {
        "name": cat_entry["name"],
        "current": entry.get("current", 0),
        "max": entry.get("max") or cat_entry.get("max") or 1,
        "done": entry.get("done", False),
    }


async def fetch_worldbosses_looted_today(api_key: str) -> set[str]:
    """Event ids (not display names) of world bosses this account has
    already looted since the last daily reset."""
    resp = await _client.get("/account/worldbosses", headers=_auth_headers(api_key))
    resp.raise_for_status()
    return set(resp.json())


async def fetch_gem_exchange() -> dict | None:
    """Public, no key needed. Live gold<->gem exchange rates, for a
    representative quantity each direction rather than an abstract per-unit
    rate - 400 gems (the size of the smallest real-money gem purchase) for
    selling gems, and 100 gold for selling gold (i.e. buying gems), so the
    numbers reflect something a player would actually consider doing. The
    Exchange has real slippage at volume, so "coins per gem" differs
    slightly between the two calls. Currency icons come along for the ride
    so the UI can show the real Gold/Gem icons rather than text labels."""
    try:
        sell_gems_resp = await _client.get("/commerce/exchange/gems?quantity=400")
        sell_gems_resp.raise_for_status()
        sell_gold_resp = await _client.get("/commerce/exchange/coins?quantity=1000000")
        sell_gold_resp.raise_for_status()
    except httpx.HTTPStatusError:
        return None

    currencies = await _get_ref("/currencies?ids=1,4", ttl=86400)
    icons = {c["id"]: c.get("icon") for c in currencies}

    return {
        "sell_gems": 400,
        "sell_gems_for_coins": sell_gems_resp.json()["quantity"],
        "sell_gold_coins": 1000000,
        "sell_gold_for_gems": sell_gold_resp.json()["quantity"],
        "gold_icon": icons.get(1),
        "gem_icon": icons.get(4),
    }


async def fetch_prices(item_ids: list[int]) -> dict[int, dict]:
    """Public, no key needed. Returns {item_id: {"buy", "sell"}} in copper."""
    if not item_ids:
        return {}
    resp = await _client.get(f"/commerce/prices?ids={','.join(map(str, item_ids))}")
    resp.raise_for_status()
    out = {}
    for entry in resp.json():
        out[entry["id"]] = {
            "buy": entry.get("buys", {}).get("unit_price", 0),
            "sell": entry.get("sells", {}).get("unit_price", 0),
        }
    return out


async def fetch_items(item_ids: list[int]) -> dict[int, dict]:
    """Public, no key needed. Returns {item_id: {"name", "icon"}}."""
    if not item_ids:
        return {}
    data = await _get_ref(f"/items?ids={','.join(map(str, item_ids))}", ttl=86400)
    return {i["id"]: {"name": i["name"], "icon": i.get("icon"), "type": i.get("type")} for i in data}


async def fetch_all_tradeable_ids() -> list[int]:
    """Public. Every item id currently listed on the Trading Post (~28k as of
    2026-09) - no prices, just ids. Cheap on its own; the expensive part is
    bulk-fetching prices for all of them afterwards."""
    resp = await _client.get("/commerce/prices")
    resp.raise_for_status()
    return resp.json()


async def _fetch_prices_raw(item_ids: list[int]) -> list[dict]:
    """Like fetch_prices(), but keeps the full API shape (including order-book
    quantities) instead of collapsing to just {buy, sell} - needed for the
    flip scanner's liquidity filter."""
    if not item_ids:
        return []
    resp = await _client.get(f"/commerce/prices?ids={','.join(map(str, item_ids))}")
    resp.raise_for_status()
    return resp.json()


async def search_recipe_id(output_item_id: int) -> int | None:
    resp = await _client.get(f"/recipes/search?output={output_item_id}")
    resp.raise_for_status()
    ids = resp.json()
    return ids[0] if ids else None


async def fetch_craft_profit(item_id: int, buy_price: int) -> dict | None:
    """Returns {"ingredients": [{"name","icon","qty","unit_price"}, ...],
    "craft_cost", "revenue", "profit"} for the given item's own crafting
    recipe, or None if it has no recipe, or if any ingredient can't be priced
    (e.g. account-bound intermediate materials with no TP listing - happens
    for some ascended-tier components, see project notes). revenue is the
    item's own buy-order price after the 15% TP cut, same convention as the
    Items to Flip scan below - "would crafting this from scratch beat buying
    the finished item outright."
    """
    recipe_id = await search_recipe_id(item_id)
    if recipe_id is None:
        return None

    resp = await _client.get(f"/recipes/{recipe_id}")
    resp.raise_for_status()
    recipe = resp.json()

    ing_ids = [ing["item_id"] for ing in recipe["ingredients"]]
    prices = await fetch_prices(ing_ids)
    items = await fetch_items(ing_ids)

    ingredients = []
    cost = 0
    for ing in recipe["ingredients"]:
        iid = ing["item_id"]
        price = prices.get(iid)
        if price is None or price["sell"] == 0:
            return None  # an ingredient isn't tradeable - can't cost this recipe
        info = items.get(iid, {})
        cost += price["sell"] * ing["count"]
        ingredients.append({
            "name": info.get("name", f"Item {iid}"), "icon": info.get("icon"),
            "qty": ing["count"], "unit_price": price["sell"],
        })

    revenue = round(buy_price * 0.85)
    return {"ingredients": ingredients, "craft_cost": cost, "revenue": revenue, "profit": revenue - cost}


async def scan_flip_candidates(limit: int = 20) -> list[dict]:
    """Live scan of the *entire* Trading Post for buy-order -> relist-to-sell
    margins (profit = sell*0.85 - buy), restricted to type=="CraftingMaterial".

    That restriction matters: an unrestricted first pass during development
    surfaced almost entirely random Fine/Masterwork/Exotic gear drops and
    upgrade components sitting at a suspiciously uniform ~100% "profit" -
    the signature of stale, essentially-dead listings (nobody actually
    re-lists these), not real flips. Filtering to genuine crafting materials
    excludes that noise.

    The official API exposes no sold/bought-per-day history (that's
    gw2bltc's own years of continuous polling, which this project doesn't
    have), so order-book depth (quantity) is used as the best available
    liquidity proxy instead of confirmed turnover - flagged to the user in
    the UI rather than presented as a guarantee.

    Heavy: ~140 price-fetch calls plus item-info calls for the pre-filtered
    pool. Call this on its own slow schedule (see
    settings.flip_scan_interval_minutes), not on every request.
    """
    all_ids = await fetch_all_tradeable_ids()

    candidates = []
    for i in range(0, len(all_ids), 200):
        chunk = all_ids[i:i + 200]
        for entry in await _fetch_prices_raw(chunk):
            buy = entry.get("buys", {}).get("unit_price", 0)
            sell = entry.get("sells", {}).get("unit_price", 0)
            buy_qty = entry.get("buys", {}).get("quantity", 0)
            sell_qty = entry.get("sells", {}).get("quantity", 0)
            if buy <= 0 or sell <= 0:
                continue
            profit = sell * 0.85 - buy
            profit_pct = (profit / buy) * 100 if buy else 0
            if profit_pct < 3 or profit_pct > 80:
                continue
            if buy_qty < 300 or sell_qty < 300:
                continue
            if profit < 20:
                continue
            candidates.append({
                "id": entry["id"], "buy": buy, "sell": sell,
                "buy_qty": buy_qty, "sell_qty": sell_qty,
                "profit": round(profit), "profit_pct": round(profit_pct, 1),
            })

    # Restrict to real crafting materials only (official `type` field) -
    # fetch item info for the pre-filtered candidate pool.
    cand_ids = [c["id"] for c in candidates]
    items_by_id: dict[int, dict] = {}
    for i in range(0, len(cand_ids), 200):
        chunk = cand_ids[i:i + 200]
        items_by_id.update(await fetch_items(chunk))

    materials = []
    for c in candidates:
        item = items_by_id.get(c["id"])
        if not item or item.get("type") != "CraftingMaterial":
            continue
        c["name"] = item["name"]
        c["icon"] = item.get("icon")
        materials.append(c)

    materials.sort(key=lambda c: c["profit_pct"], reverse=True)
    top = materials[:limit]

    # Enrich the shortlist with craft-cost/profit, same as the watchlist -
    # only for the final `limit` items, not the whole candidate pool, since
    # fetch_craft_profit does its own extra API calls per item.
    for c in top:
        try:
            c["recipe"] = await fetch_craft_profit(c["id"], c["buy"])
        except Exception:
            c["recipe"] = None

    return top
