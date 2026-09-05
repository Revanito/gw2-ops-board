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
"""


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
