import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    discord_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    avatar_hash TEXT,
    encrypted_api_key TEXT,
    api_key_added_at TEXT
);

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id TEXT NOT NULL,
    text TEXT NOT NULL,
    link TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    achievement_id INTEGER,
    FOREIGN KEY (discord_id) REFERENCES users(discord_id)
);

-- One row per refresh_public_data() tick (every settings.refresh_interval_minutes),
-- so the "last 30 days" gem exchange chart is built from data this app actually
-- collected itself - the official API has no historical endpoint to read this from.
CREATE TABLE IF NOT EXISTS gem_exchange_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    sell_gems_for_coins INTEGER NOT NULL,
    sell_gold_for_gems INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gem_exchange_history_ts ON gem_exchange_history(ts);

-- Personal gemstore wishlist, replacing the old everyone-shares-one-list
-- favorites.json for logged-in users (favorites.json now only backs the
-- small default list shown to logged-out visitors).
CREATE TABLE IF NOT EXISTS user_favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(discord_id, item_name),
    FOREIGN KEY (discord_id) REFERENCES users(discord_id)
);
"""

# Kept a little past 30 days so a "last 30 days" chart never has a thin
# leading edge right at the boundary.
_GEM_HISTORY_RETENTION_DAYS = 35

# Snapshot of favorites.json's contents from just before personal favorites
# shipped - a one-time seed so whoever already had an account doesn't lose
# their curated list when it moves from the shared file to a personal one.
# Deliberately hardcoded rather than read from favorites.json, since that
# file's own contents change independently after this (it's now the
# logged-out default list, not a migration source).
_LEGACY_FAVORITES_SEED = [
    "Wandering Weapon Master Outfit",
    "Home Instance Node Pack",
    "Home Instance Contract Pack",
    "Copper-Fed Salvage-o-Matic",
    "Shared Inventory Slot",
    "Infinite Skyscale Gathering Tools",
    "Infinite Herald of Aurene Gathering Tools",
    "Infinite Holy Barrage Gathering Tools",
    "Infinite Metal Legion Gathering Tools",
    "Grand Lion Griffon Skin",
    "Irascible Noble Skyscale",
    "Regal Moth Skyscale Skin",
    "Floating Garden Skiff Skin",
    "Vermilion Wings Backpack",
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # CREATE TABLE IF NOT EXISTS only helps on a brand-new DB - an
        # already-deployed todos table predates achievement_id, so it needs
        # a real migration rather than relying on the schema script above.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(todos)")}
        if "achievement_id" not in cols:
            conn.execute("ALTER TABLE todos ADD COLUMN achievement_id INTEGER")

        # One-time carryover: if user_favorites has never been touched at all,
        # seed every existing account with the pre-personal-favorites list so
        # nobody's curated wishlist just vanishes the day this feature ships.
        (favorites_ever_used,) = conn.execute("SELECT COUNT(*) FROM user_favorites").fetchone()
        if favorites_ever_used == 0:
            now = datetime.now(timezone.utc).isoformat()
            existing_users = [row["discord_id"] for row in conn.execute("SELECT discord_id FROM users")]
            for discord_id in existing_users:
                for name in _LEGACY_FAVORITES_SEED:
                    conn.execute(
                        "INSERT OR IGNORE INTO user_favorites (discord_id, item_name, created_at) "
                        "VALUES (?, ?, ?)",
                        (discord_id, name, now),
                    )


def upsert_user(discord_id: str, username: str, avatar_hash: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (discord_id, username, avatar_hash) VALUES (?, ?, ?)
               ON CONFLICT(discord_id) DO UPDATE SET username = ?, avatar_hash = ?""",
            (discord_id, username, avatar_hash, username, avatar_hash),
        )


def get_user(discord_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,)).fetchone()


def set_api_key(discord_id: str, encrypted_key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET encrypted_api_key = ?, api_key_added_at = ? WHERE discord_id = ?",
            (encrypted_key, now, discord_id),
        )


def clear_api_key(discord_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET encrypted_api_key = NULL, api_key_added_at = NULL WHERE discord_id = ?",
            (discord_id,),
        )


def add_todo(discord_id: str, text: str, link: str | None, achievement_id: int | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO todos (discord_id, text, link, created_at, achievement_id) VALUES (?, ?, ?, ?, ?)",
            (discord_id, text, link, now, achievement_id),
        )


def list_todos(discord_id: str) -> list[sqlite3.Row]:
    """Unfinished items first (oldest first within each group), so the
    to-do list itself doesn't need any client-side sorting - a checked-off
    item sinks below the active ones but stays visible rather than
    disappearing."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM todos WHERE discord_id = ? ORDER BY done ASC, id ASC",
            (discord_id,),
        ).fetchall()


def toggle_todo(discord_id: str, todo_id: int) -> None:
    # discord_id is part of the WHERE clause (not just id) so one user can
    # never toggle/delete another user's item by guessing/reusing an id.
    with get_conn() as conn:
        conn.execute(
            "UPDATE todos SET done = NOT done WHERE id = ? AND discord_id = ?",
            (todo_id, discord_id),
        )


def delete_todo(discord_id: str, todo_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM todos WHERE id = ? AND discord_id = ?", (todo_id, discord_id))


def record_gem_exchange_sample(sell_gems_for_coins: int, sell_gold_for_gems: int) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    cutoff = now - _GEM_HISTORY_RETENTION_DAYS * 86400
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO gem_exchange_history (ts, sell_gems_for_coins, sell_gold_for_gems) "
            "VALUES (?, ?, ?)",
            (now, sell_gems_for_coins, sell_gold_for_gems),
        )
        conn.execute("DELETE FROM gem_exchange_history WHERE ts < ?", (cutoff,))


def add_favorite(discord_id: str, item_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        # OR IGNORE: re-adding a name already on the list is a silent no-op
        # rather than a duplicate row or a UNIQUE-constraint error.
        conn.execute(
            "INSERT OR IGNORE INTO user_favorites (discord_id, item_name, created_at) VALUES (?, ?, ?)",
            (discord_id, item_name, now),
        )


def list_favorites(discord_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, item_name FROM user_favorites WHERE discord_id = ? ORDER BY id ASC",
            (discord_id,),
        ).fetchall()


def list_all_favorite_names() -> list[str]:
    """Every distinct item name any user has favorited, across all accounts -
    used to warm the shared price/icon cache for exactly the items actually
    in use, rather than looking anything up per-request."""
    with get_conn() as conn:
        return [row["item_name"] for row in conn.execute("SELECT DISTINCT item_name FROM user_favorites")]


def remove_favorite(discord_id: str, favorite_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM user_favorites WHERE id = ? AND discord_id = ?",
            (favorite_id, discord_id),
        )


def get_gem_exchange_history(days: int = 30) -> list[sqlite3.Row]:
    cutoff = int(datetime.now(timezone.utc).timestamp()) - days * 86400
    with get_conn() as conn:
        return conn.execute(
            "SELECT ts, sell_gems_for_coins, sell_gold_for_gems FROM gem_exchange_history "
            "WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
