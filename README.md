# gw2-ops-board

A Guild Wars 2 companion board: a public world boss/meta-event timeline, a gemstore tracker
that flags your own wishlist items when they're on sale, a Trading Post watchlist with
craft-profit math, and a live "Items to Flip" scanner across the whole Trading Post — plus,
for logged-in guild members, a private per-account dashboard, character list, and Material
Storage view built from each member's own GW2 API key.

## Sections

**Public, no login** (`/`, `/market`):
- **World Boss & Meta Event Timeline** — a Gantt-style, lebusmagique-inspired timeline covering
  the daily world boss rotation plus 2-hour meta-event cycles across 41 zones spanning all 10
  expansions/living-world releases (Core Tyria through Visions of Eternity), with per-category
  color coding, show/hide filters, and a live "now" line rendered in the viewer's own local
  time (a separate clock badge still shows raw server/UTC time). Source data is static
  (`app/data/world_bosses.json`, `app/data/meta_events.json`) — no fetching involved.
- **Gemstore — Favorites On Sale Now** — pulled from thatshaman.com's gem store rotation feed
  (`app/gemstore_client.py`) and cross-referenced against `favorites.json`. Gem prices are
  best-effort, scraped from each item's own wiki page (there's no official API for gem store
  pricing).
- **Trading Post Watchlist** — live buy/sell prices from the official GW2 API for the item IDs
  in `watchlist.json`, with a Craft Cost/Profit column (and ingredient breakdown) for any item
  that has a known crafting recipe.
- **Items to Flip** — a live scan of the entire Trading Post (~28k items) for buy-order →
  relist-to-sell margins, restricted to actual crafting materials to filter out stale
  gear-drop noise. Runs on its own background schedule since it's much heavier than the
  gemstore/watchlist refresh (`FLIP_SCAN_INTERVAL_MINUTES` in `.env`, default hourly).

**Private, Discord login required**:
- `/settings` — paste your own GW2 API key (create one at
  [account.arena.net/applications](https://account.arena.net/applications) with the
  `account`, `wallet`, `progression`, `unlocks`, `characters`, `builds`, `inventories`
  permissions). Stored encrypted at rest (Fernet); only ever decrypted server-side to render
  your own private pages below.
- `/dashboard` — account summary, wallet (a headline row for Gold/Karma/Laurel/Gem, everything
  else as a compact list), and today's Wizard's Vault objectives with live progress (reflects
  in-game completions on reload, not a cached snapshot).
- `/characters` — every character on the account: level, race, profession, current PvE elite
  specialization, and every crafting discipline the character has trained (not just the 2
  currently equipped in-game), shown as `Discipline rating/500`.
- `/materials` — live Material Storage contents, grouped and ordered the same way the in-game
  tab is (needs the `inventories` scope above).

The GW2 API is read-only end to end — there's no endpoint that can move items, spend
currency, or otherwise act on an account — so a leaked key can only expose information, never
let someone act on the account. It still deserves the encryption-at-rest treatment it gets
here, since wallet contents, characters, and Material Storage are still personal info.

## A few things worth knowing about the GW2 API

Discovered the hard way while building the character/materials pages, since several of these
aren't obvious from the endpoint names alone:
- `characters` only covers the endpoints like `/characters/:id/core`, `/crafting`,
  `/equipment`, `/inventory`. Build/loadout data (`/characters/:id/specializations`,
  `/buildtabs`, `/skills`, `/training`) needs the separate `builds` scope instead.
- Bank and Material Storage (`/account/bank`, `/account/materials`) need the `inventories`
  scope — there's no scope literally called "bank".
- Several sub-resource endpoints wrap their payload under a key matching the endpoint's own
  name rather than returning it bare — `/characters/:id/specializations` returns
  `{"specializations": {"pve": [...], ...}}`, and `/characters/:id/crafting` returns
  `{"crafting": [...]}`, not a bare list. `gw2_api.py`'s character-fetching code checks for
  the wrapper and falls back to the unwrapped shape defensively.
- Character names routinely contain spaces/punctuation and must be percent-encoded before
  going into a URL path.

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

See [deploy/README.md](deploy/README.md) — self-hosted behind an existing nginx
reverse-proxy LXC, running as one more `docker-compose` service on an existing Docker host
rather than a dedicated LXC, same general pattern as
[read-later](https://github.com/Revanito/read-later).

## Notes

- `main.py` runs two independent background loops: one refreshes the gemstore/TP watchlist
  data (`REFRESH_INTERVAL_MINUTES`, default 30 min), the other rescans the whole Trading Post
  for flip candidates (`FLIP_SCAN_INTERVAL_MINUTES`, default 60 min) — kept separate since the
  flip scan is far heavier (~140+ API calls). The public pages render fine even before the
  first refresh completes, or if a source is temporarily down (each fetch is wrapped so one
  failing source doesn't blank the rest of the page).
- `favorites.json` / `watchlist.json` live at the repo root for easy editing without touching
  code, and are bind-mounted into the container.
- A full-page loading overlay (`app/static/loading.js`) shows on any navigation click or form
  submit, since a few authenticated pages make several sequential GW2 API calls and can take
  a couple of seconds — without it, a slow load looks like the click did nothing.
