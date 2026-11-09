# Deployment

Two containers behind the existing Caddy on the host. Both bind to loopback;
Caddy terminates TLS and proxies `/api/*` to FastAPI and everything else to
Next.js.

```bash
# on the host, once
sudo mkdir -p /srv/dextrader
sudo chown "$USER":"$USER" /srv/dextrader
git clone https://github.com/caldefoc/DexTrader.git /srv/dextrader
cd /srv/dextrader
cp .env.example .env      # then set DEMO_MODE=1 and NEXT_PUBLIC_DEMO_MODE=1
docker compose up -d --build
```

Then append `deploy/Caddyfile.snippet` to `/etc/caddy/Caddyfile` and reload:

```bash
sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%Y%m%d-%H%M%S)"
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Notes

- `NEXT_PUBLIC_DEMO_MODE` and `NEXT_PUBLIC_BACKEND_URL` are **build-time**.
  Changing either requires `docker compose build frontend` (a restart is not
  enough).
- Demo state (virtual portfolio) lives in the `dextrader-state` volume at
  `/data`. `docker compose down -v` would delete it.
- One Uvicorn worker on purpose: state is JSON files, not a database.
- The clone contains no runtime data: `trades.json`, `agents.log`,
  `agent_state.json`, `price_history.json` and `demo_portfolio.json` are
  gitignored and absent after a fresh clone.
- Update: `cd /srv/dextrader && git pull && docker compose up -d --build`.
