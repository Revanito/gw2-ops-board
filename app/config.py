from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str
    # Restrict login to members of this Discord guild. Leave empty to allow any Discord account.
    discord_guild_id: str = ""

    # Signs the session cookie (Starlette SessionMiddleware). Generate with:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    session_secret: str

    # Encrypts stored GW2 API keys at rest (Fernet). Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str

    db_path: str = "/data/gw2-ops-board.db"

    # How often the public sections (gemstore tracker, TP watchlist) refresh in the background.
    refresh_interval_minutes: int = 30

    # Scanning the whole Trading Post (~28k items) for "Items to Flip" is much
    # heavier than the gemstore/watchlist refresh above, so it runs on its own,
    # slower schedule - hourly by default.
    flip_scan_interval_minutes: int = 60


settings = Settings()
