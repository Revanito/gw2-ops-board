# Deploying behind a reverse proxy

Two hosts involved:

- **The nginx host** — your existing shared nginx LXC that already terminates TLS for
  `later`/`r6`/`feeds`/etc.
- **The app host** — your existing `discord-1min-proxy` LXC, which already runs Docker for
  your other projects. This app is just one more `docker-compose` service there; no new LXC
  needed. Before deploying, confirm port `8087` (this app's host-side port, see
  `docker-compose.yml`) isn't already used by something else on that box — pick a different
  host port in `docker-compose.yml` and in the nginx vhost below if it is.

## 1. App container

On the app host (`discord-1min-proxy`), alongside your other docker-compose projects:

```
git clone https://github.com/Revanito/gw2-ops-board.git
cd gw2-ops-board
cp .env.example .env
# Fill in DISCORD_CLIENT_ID/SECRET, DISCORD_REDIRECT_URI, DISCORD_GUILD_ID,
# and generate SESSION_SECRET / FERNET_KEY (commands are in the .env.example comments).
docker compose up -d --build
curl -s localhost:8087 | head -5   # sanity check it's actually serving
```

## 2. DNS

Point your chosen subdomain (e.g. `gw2.vaultinc.fr`) at your home public IP, same as any
other reverse-proxied service you already run.

## 3. nginx vhost, on the nginx host

```
sudo cp deploy/nginx-reverse-proxy.conf /etc/nginx/sites-available/gw2
sudo ln -s /etc/nginx/sites-available/gw2 /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Edit the copied file first to replace `<YOUR_DOMAIN>` and `<APP_HOST_IP>` with your real values.
**Don't skip the `sites-enabled` symlink** — a vhost sitting only in `sites-available` loads
silently as nothing; `nginx -t` will report "syntax ok" either way.

## 4. TLS

```
sudo certbot --nginx -d gw2.vaultinc.fr
```

Start from this **fresh, pre-certbot** vhost rather than copying an already-certbot-processed
sibling file — the sibling's `ssl_certificate` paths point at its own domain and will break
`nginx -t` before certbot gets a chance to fix them.

## 5. Discord application

At [discord.com/developers/applications](https://discord.com/developers/applications):
create an application → OAuth2 → add redirect `https://<your-domain>/auth/callback` → copy
the Client ID/Secret into `.env`. If you want to restrict login to your guild's members, add
your guild's ID to `DISCORD_GUILD_ID` (right-click the guild in Discord with Developer Mode on
→ Copy Server ID).

## 6. Verify

```
curl -I https://gw2.vaultinc.fr
```

Should return `200 OK`, not nginx's default page or a `502` (502 means nginx can't reach the
app host on the expected port — check the container is up and no firewall rule is blocking it).
