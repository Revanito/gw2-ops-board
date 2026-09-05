"""Discord OAuth2 authorization-code flow for guild-member login.

Only used to identify who's logging in (and optionally check guild
membership) - no bot token, no message/guild-management scopes.
"""
from urllib.parse import urlencode

import httpx

from config import settings

AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
API_BASE = "https://discord.com/api/v10"

SCOPES = "identify" + (" guilds" if settings.discord_guild_id else "")


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "prompt": "none",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> str:
    """Returns the access token for the newly-authorized user."""
    data = {
        "client_id": settings.discord_client_id,
        "client_secret": settings.discord_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.discord_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp.raise_for_status()
        return resp.json()["access_token"]


async def fetch_identity(access_token: str) -> dict:
    """Returns {"id", "username", "avatar_hash"} for the logged-in Discord user."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API_BASE}/users/@me", headers=headers)
        resp.raise_for_status()
        user = resp.json()
    return {
        "id": user["id"],
        "username": user.get("global_name") or user["username"],
        "avatar_hash": user.get("avatar"),
    }


async def is_guild_member(access_token: str, guild_id: str) -> bool:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API_BASE}/users/@me/guilds", headers=headers)
        resp.raise_for_status()
        guilds = resp.json()
    return any(g["id"] == guild_id for g in guilds)
