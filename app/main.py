import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.middleware.sessions import SessionMiddleware

import boss_timers
import discord_auth
import gemstore_client
import gw2_api
import meta_events
import wiki_client
from config import settings
from crypto import decrypt, encrypt
from db import clear_api_key, get_user, init_db, set_api_key, upsert_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gw2-ops-board")

# favorites.json/watchlist.json live at the repo root for easy editing, and are
# bind-mounted into the container at this same path by docker-compose.yml.
CONFIG_DIR = Path(__file__).parent

public_cache: dict = {
    "gemstore_favorites": [], "gemstore_promotions": [], "watchlist": [], "updated_at": None,
    "items_to_flip": [], "flip_updated_at": None,
}

# thatshaman's own rotating single-item promotional showcase - independent
# of favorites.json, shown as "what's newly on sale" regardless of whether
# it happens to be on anyone's personal wishlist.
PROMOTIONS_CATEGORY = "New Items"


def _load_json_list(path: Path, key: str) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))[key]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        log.exception("couldn't read %s", path)
        return []


async def refresh_public_data() -> None:
    try:
        favorite_names = _load_json_list(CONFIG_DIR / "favorites.json", "items")
        active = await gemstore_client.fetch_gemstore_schedule()

        matches = gemstore_client.match_favorites(active, favorite_names)
        for entry in matches:
            entry["price"] = await wiki_client.fetch_gem_price(entry["name"])
        public_cache["gemstore_favorites"] = matches

        promotions = gemstore_client.filter_by_category(active, PROMOTIONS_CATEGORY)
        for entry in promotions:
            entry["price"] = await wiki_client.fetch_gem_price(entry["name"])
        public_cache["gemstore_promotions"] = promotions
    except Exception:
        log.exception("gemstore refresh failed")

    try:
        item_ids = _load_json_list(CONFIG_DIR / "watchlist.json", "item_ids")
        prices = await gw2_api.fetch_prices(item_ids)
        items = await gw2_api.fetch_items(item_ids)
        watchlist = []
        for item_id in item_ids:
            info = items.get(item_id, {})
            price = prices.get(item_id, {})
            buy, sell = price.get("buy", 0), price.get("sell", 0)
            try:
                recipe = await gw2_api.fetch_craft_profit(item_id, buy) if buy else None
            except Exception:
                log.exception("craft-profit lookup failed for item %s", item_id)
                recipe = None
            watchlist.append({
                "id": item_id,
                "name": info.get("name", f"Item {item_id}"),
                "icon": info.get("icon"),
                "buy": buy,
                "sell": sell,
                "recipe": recipe,
            })
        public_cache["watchlist"] = watchlist
    except Exception:
        log.exception("TP watchlist refresh failed")

    public_cache["updated_at"] = datetime.now(timezone.utc).isoformat()


async def refresh_flip_candidates() -> None:
    """Separate from refresh_public_data() - scanning the whole Trading Post
    is much heavier (~140+ API calls) than the gemstore/watchlist refresh, so
    it runs on its own slower schedule (settings.flip_scan_interval_minutes,
    default hourly) rather than the shared one."""
    try:
        public_cache["items_to_flip"] = await gw2_api.scan_flip_candidates(limit=20)
    except Exception:
        log.exception("Items to Flip scan failed")
    public_cache["flip_updated_at"] = datetime.now(timezone.utc).isoformat()


async def _refresh_loop() -> None:
    while True:
        await asyncio.sleep(settings.refresh_interval_minutes * 60)
        await refresh_public_data()


async def _flip_scan_loop() -> None:
    while True:
        await asyncio.sleep(settings.flip_scan_interval_minutes * 60)
        await refresh_flip_candidates()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await refresh_public_data()  # best-effort initial fill; an empty cache still renders fine
    refresh_task = asyncio.create_task(_refresh_loop())
    # The flip scan is heavy (~140+ API calls, roughly a minute) - kicked off
    # in the background rather than awaited, so app startup isn't blocked on
    # it. The page renders fine with an empty Items to Flip list until the
    # first scan finishes.
    flip_task = asyncio.create_task(refresh_flip_candidates())
    flip_loop_task = asyncio.create_task(_flip_scan_loop())
    yield
    refresh_task.cancel()
    flip_task.cancel()
    flip_loop_task.cancel()


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def format_coins(copper: int) -> Markup:
    """Renders a copper amount as GW2's own gold/silver/copper display, e.g.
    2g 3s 45c - matching the game's own currency convention rather than a
    flat decimal-gold format, which rounds cheap crafting materials (worth a
    handful of copper) away to "0.00g"."""
    copper = round(copper)
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    g, rem = divmod(copper, 10000)
    s, c = divmod(rem, 100)
    parts = []
    if g:
        parts.append(f'<span class="coin gold">{g}g</span>')
    if s or g:
        parts.append(f'<span class="coin silver">{s}s</span>')
    parts.append(f'<span class="coin copper">{c}c</span>')
    return Markup(sign + " ".join(parts))


templates.env.filters["coins"] = format_coins


def current_user(request: Request):
    user_id = request.session.get("user_id")
    return get_user(user_id) if user_id else None


async def _safe(coro, default, label, discord_id):
    """Runs one GW2 API call, logging and falling back to `default` instead
    of blowing up the whole page if that one call fails - used to fetch
    several independent things concurrently via asyncio.gather()."""
    try:
        return await coro
    except Exception:
        log.exception("%s failed for %s", label, discord_id)
        return default


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": current_user(request),
        "world_bosses": boss_timers.load_world_boss_schedule()["bosses"],
        "world_boss_icon": meta_events.WORLD_BOSS_ICON,
        "world_boss_hue": meta_events.WORLD_BOSS_HUE,
        "category_order": meta_events.CATEGORY_ORDER,
        "zones_by_category": meta_events.zones_by_category(),
    })


@app.get("/market")
def market(request: Request):
    return templates.TemplateResponse("market.html", {
        "request": request,
        "user": current_user(request),
        "gemstore_favorites": public_cache["gemstore_favorites"],
        "gemstore_promotions": public_cache["gemstore_promotions"],
        "watchlist": public_cache["watchlist"],
        "items_to_flip": public_cache["items_to_flip"],
        "updated_at": public_cache["updated_at"],
        "flip_updated_at": public_cache["flip_updated_at"],
    })


@app.get("/login")
def login(request: Request):
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(discord_auth.build_authorize_url(state))


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = ""):
    if not code or not state or state != request.session.get("oauth_state"):
        return RedirectResponse("/?error=login_failed")
    request.session.pop("oauth_state", None)

    try:
        access_token = await discord_auth.exchange_code(code)
        if settings.discord_guild_id and not await discord_auth.is_guild_member(access_token, settings.discord_guild_id):
            return RedirectResponse("/?error=not_a_guild_member")
        identity = await discord_auth.fetch_identity(access_token)
    except Exception:
        log.exception("discord auth callback failed")
        return RedirectResponse("/?error=login_failed")

    upsert_user(identity["id"], identity["username"], identity["avatar_hash"])
    request.session["user_id"] = identity["id"]
    return RedirectResponse("/settings")


@app.get("/settings")
def settings_page(request: Request, error: str = "", success: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("settings.html", {
        "request": request, "user": user, "error": error, "success": success,
    })


@app.post("/settings/api-key")
async def save_api_key(request: Request, api_key: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    api_key = api_key.strip()
    result = await gw2_api.validate_token(api_key)
    if not result["ok"]:
        return RedirectResponse(f"/settings?error={result['error']}", status_code=303)
    if result["missing_scopes"]:
        missing = ", ".join(result["missing_scopes"])
        return RedirectResponse(f"/settings?error=key is missing required scopes: {missing}", status_code=303)

    set_api_key(user["discord_id"], encrypt(api_key))
    return RedirectResponse("/settings?success=1", status_code=303)


@app.post("/settings/api-key/delete")
def delete_api_key(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    clear_api_key(user["discord_id"])
    return RedirectResponse("/settings?success=removed", status_code=303)


@app.get("/dashboard")
async def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login")
    if not user["encrypted_api_key"]:
        return RedirectResponse("/settings?error=add your GW2 API key first")

    api_key = decrypt(user["encrypted_api_key"])
    if not api_key:
        return RedirectResponse("/settings?error=your saved key couldn't be read, please re-add it")

    # Independent calls, run concurrently rather than one after another -
    # this was previously the main reason the dashboard felt like it hung.
    account, wallet, vault = await asyncio.gather(
        _safe(gw2_api.fetch_account(api_key), None, "fetch_account", user["discord_id"]),
        _safe(gw2_api.fetch_wallet(api_key), [], "fetch_wallet", user["discord_id"]),
        _safe(gw2_api.fetch_wizards_vault_daily(api_key), None, "fetch_wizards_vault_daily", user["discord_id"]),
    )

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "account": account, "wallet": wallet, "vault": vault,
    })


@app.get("/characters")
async def characters_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login")
    if not user["encrypted_api_key"]:
        return RedirectResponse("/settings?error=add your GW2 API key first")

    api_key = decrypt(user["encrypted_api_key"])
    if not api_key:
        return RedirectResponse("/settings?error=your saved key couldn't be read, please re-add it")

    characters = await _safe(gw2_api.fetch_characters(api_key), [], "fetch_characters", user["discord_id"])

    return templates.TemplateResponse("characters.html", {
        "request": request, "user": user, "characters": characters,
    })


@app.get("/materials")
async def materials(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login")
    if not user["encrypted_api_key"]:
        return RedirectResponse("/settings?error=add your GW2 API key first")

    api_key = decrypt(user["encrypted_api_key"])
    if not api_key:
        return RedirectResponse("/settings?error=your saved key couldn't be read, please re-add it")

    categories = await _safe(gw2_api.fetch_materials(api_key), [], "fetch_materials", user["discord_id"])

    return templates.TemplateResponse("materials.html", {
        "request": request, "user": user, "categories": categories,
    })
