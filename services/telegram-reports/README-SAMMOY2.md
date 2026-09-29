# SAMMOY2 reporting migration

The legacy per-post Report API, aggregator, owner pairing, daily reports and
health notifications are retained. Docker replaces the host systemd setup agent.
The container runs as UID 10001; it has no GPIO, Docker socket or host service
control. Its database login can SELECT only payments, wash_sessions, mode_usage
and system_events, with default_transaction_read_only enabled.

## Deployment on each station

Start the usual PostgreSQL and wash-engine services first, so the ledger tables
exist. From the project root:

```sh
sudo python3 deploy/install-reports.py
sudo docker compose build telegram-reports wash-engine kiosk-ui
sudo docker compose up -d telegram-reports wash-engine kiosk-ui
```

The provisioning script generates and saves secrets in the existing private
`.env` without printing them. It configures the LAN address/range from the host
route. Run it again after a LAN address change. Automatic discovery supports
IPv4 networks of /24 or smaller, matching the legacy installer.

Complete `/install` on every station using the real activation server or signed
commissioning response. Every station of a wash needs the same site identity and
site token, and a unique station number. The backend synchronizes report identity
in the background. The report key is derived exactly as in the old project:
SHA256(`rtu-wash-local-reports-v1:` + site_token), retaining legacy compatibility.
No site token is exposed in the Owner UI.

On station 1, open Owner → Telegram, enter the BotFather token, pair the owner via
QR, and choose automatic station discovery. Reports are sent at 21:00 Asia/Tashkent.
Owner → Reports → All stations works independently of whether a bot is configured.
The report API is published on the selected LAN address, port 8091, with bearer
key authentication. Setup is reachable only on the Docker network through the
Owner-authenticated wash-engine proxy; the hub listens on container loopback.

Known offline stations remain in the configuration after discovery. Duplicate
station numbers abort discovery without overwriting the previous list. Aggregated
report identities are checked against configured site/station IDs. Missing posts
are shown as unavailable, never as zero revenue. Pairing links expire in 10 minutes,
are single-use, and are invalidated on owner reset. A change of site identity disables
the bot and revokes the previous pairing.

The legacy `app/setup_agent.py` is retained for reference/tests, but is not run in
SAMMOY2. The new entry point is `app/container_setup.py`. Dependencies are pinned in
`requirements.lock`. Persistent config and pairing data use the `reports-data` volume.

## Verification and outstanding commissioning

26 isolated tests cover legacy aggregation/pairing/notifications plus setup auth,
secret redaction, pairing invalidation, discovery, duplicate IDs and mismatched
report identities. On the development Radxa, Report API reads the actual ledger;
the SQL role has no write privileges.

The current Radxa has no activated site identity or Telegram token. Actual
multi-board discovery and Telegram delivery require commissioning and owner
pairing. No messages have been sent during development. Live tariffs, card balances
and wash state-machine rules were not changed by this migration.
