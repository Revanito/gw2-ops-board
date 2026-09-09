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
"""

# Kept a little past 30 days so a "last 30 days" chart never has a thin
# leading edge right at the boundary.
_GEM_HISTORY_RETENTION_DAYS = 35


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


def get_gem_exchange_history(days: int = 30) -> list[sqlite3.Row]:
    cutoff = int(datetime.now(timezone.utc).timestamp()) - days * 86400
    with get_conn() as conn:
        return conn.execute(
            "SELECT ts, sell_gems_for_coins, sell_gold_for_gems FROM gem_exchange_history "
            "WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
