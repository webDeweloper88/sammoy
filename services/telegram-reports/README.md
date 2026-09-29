# RTU WASH Local Reports + Telegram Owner Bot

Optional read-only reporting add-on for RTU WASH Edge. One post acts as a Local Hub, collects
reports from a configurable number of posts over the LAN, and sends deterministic owner reports via
Telegram long polling. The wash controller remains fully independent if this project stops.

## Safety boundary

- No GPIO, relay, credit, tariff mutation, Click control, or write endpoints.
- Current tariffs are exposed read-only through authenticated Report APIs and the paired-owner bot.
- Postgres production adapter starts each report transaction as `READ ONLY`.
- Report API is LAN-only and requires a per-post Bearer key.
- Telegram answers only the paired owner in a private chat.
- Pairing tokens are random, hashed in SQLite, expire after 10 minutes, and are single-use.
- No VPS, webhook, Node-RED, cloud database, or AI dependency.

## Components

- `app.report_api`: per-post read-only API, backed by RTU WASH Postgres or deterministic demo data.
- `app.hub`: concurrent aggregation with retry, partial-result handling, and short cache.
- `app.telegram_bot`: aiogram long-polling bot and secure owner pairing.
- `app.setup_agent`: localhost-only commissioning API; validates BotFather tokens and manages services.
- `rtuwashctl`: local pairing and owner management.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp config/env.example .env
cp config/posts.example.yaml config/posts.yaml
.venv/bin/pytest
```

Run the demo post and hub:

```bash
set -a; source .env; set +a
.venv/bin/uvicorn app.report_api.main:app --port 8091
.venv/bin/uvicorn app.hub.main:app --port 8092
```

## VM or Orange Pi install

```bash
sudo ./scripts/install.sh --role post
sudo ./scripts/install.sh --role hub
```

For a production Orange Pi / Golden Image, use the wrapper. It creates a dedicated read-only
PostgreSQL login, installs the local setup API, and leaves Hub/Bot disabled:

```bash
sudo ./scripts/install-orange.sh
```

The Orange `/install` wizard allows Telegram setup only on Post 1. The recommended flow creates a
random, single-use local URL that expires after 10 minutes. The installer scans its QR code with a
phone on the same LAN and pastes the BotFather token there. Manual touch entry remains available as a
fallback. The token is validated through Telegram `getMe`, stored root-owned with mode `0640`, and
never returned to the browser. Owner pairing uses a separate hashed, single-use, 10-minute QR link.
Post 2 and later show an informational state and run only the read-only Report API; the setup backend
also rejects attempts to enable a Telegram Hub anywhere except Post 1.

Every activated post derives the same site-scoped report key locally from its existing gateway site
token. The key is one-way derived and never enters the browser. Post 1 can scan its local `/24` LAN
from `/install`; only authenticated Report APIs returning the same `site_id` are enrolled. This makes
the Telegram add-on independent from the VPS during normal operation while avoiding manual peer keys.

Secrets are stored in `/opt/rtu-wash/secrets/reports.env` with restricted permissions. Configure
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME`, then run:

```bash
sudo systemctl enable --now rtu-wash-telegram-bot
sudo -u rtu-wash-reports -H /opt/rtu-wash/reports/.venv/bin/rtuwashctl pairing create
```

The bot sends one automatic daily report at `21:00 Asia/Tashkent`. Configure this with
`AUTOMATIC_DAILY_REPORT_ENABLED` and `AUTOMATIC_DAILY_REPORT_TIME`. The last successful send date is
stored in SQLite, so service restarts do not duplicate the report.

Health monitoring checks every configured post once per minute. It sends an offline alert after
three consecutive failures and one recovery message when communication returns. Configure it with
`HEALTH_ALERTS_ENABLED`, `HEALTH_POLL_SECONDS`, and `HEALTH_FAILURE_THRESHOLD`.

## Production database role

Create a dedicated database login and grant only `CONNECT`, `USAGE` on schema `public`, and `SELECT`
on `wash_sessions`, `payments`, `mode_usage`, and `system_events`. Never reuse the wash-engine database
owner account. Set `REPOSITORY_MODE=postgres` and its DSN only in the protected environment file.

## Diagnostics

```bash
sudo /opt/rtu-wash/reports/scripts/healthcheck.sh
journalctl -u rtu-wash-report-api -u rtu-wash-local-hub -u rtu-wash-telegram-bot --since today
```
