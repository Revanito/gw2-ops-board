# gw2-ops-board

A Guild Wars 2 companion board: public world boss timers, a gemstore tracker that flags your
own wishlist items when they're on sale, and a Trading Post watchlist — plus, for logged-in
guild members, a private per-account dashboard (wallet, Wizard's Vault progress) built from
each member's own GW2 API key.

## Sections

**Public, no login** (`/`):
- **World Boss Timers** — the fixed, wiki-documented daily UTC rotation for core Tyria world
  bosses, rendered client-side with a live countdown. No fetching involved; the schedule is
  static data (`app/data/world_bosses.json`). HoT/PoF/LWS meta events (Dragon's Stand,
  Octovine, Dragonfall, etc.) aren't included — those are gated by map completion, not a fixed
  clock, so there's no reliable timer to show.
- **Gemstore — Favorites On Sale Now** — pulled from thatshaman.com's gem store rotation feed
  (`app/gemstore_client.py`) and cross-referenced against `favorites.json`. Gem prices are
  best-effort, scraped from each item's own wiki page (there's no official API for gem store
  pricing).
- **Trading Post Watchlist** — live buy/sell prices from the official GW2 API for the item IDs
  in `watchlist.json`.

**Private, Discord login required**:
- `/settings` — paste your own GW2 API key (create one at
  [account.arena.net/applications](https://account.arena.net/applications) with the
  `account`, `wallet`, `progression`, `unlocks` permissions). Stored encrypted at rest
  (Fernet); only ever decrypted server-side to render your own `/dashboard`.
- `/dashboard` — account summary, wallet, and today's Wizard's Vault objectives/progress.

The GW2 API is read-only end to end — there's no endpoint that can move items, spend
currency, or otherwise act on an account — so a leaked key can only expose information, never
let someone act on the account. It still deserves the encryption-at-rest treatment it gets
here, since wallet contents and account age are still personal info.

## Local development

```
cd app
cp ../.env.example .env   # adjust DB_PATH etc. for local use
pip install -r requirements.txt
uvicorn main:app --reload
```

`favorites.json`/`watchlist.json` are read from `app/`, so for local runs without Docker,
copy or symlink the repo-root copies in (docker-compose does this automatically via bind
mounts — see below).

## Deploy

See [deploy/README.md](deploy/README.md) — self-hosted on Proxmox behind your existing
nginx-reverse-proxy LXC, same pattern as [read-later](https://github.com/Revanito/read-later).

## Notes

- `main.py` runs a background refresh loop (`REFRESH_INTERVAL_MINUTES` in `.env`) that
  re-fetches the gemstore/TP data; the public page still renders fine even before the first
  refresh completes or if a source is temporarily down (each fetch is wrapped so one failing
  source doesn't blank the rest of the page).
- `favorites.json` / `watchlist.json` live at the repo root for easy editing without touching
  code, and are bind-mounted into the container.
