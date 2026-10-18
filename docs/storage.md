# Storage policy — 2026-10-03

Designed for working stations with 32 GB microSD. The retention periods do not
replace monitoring of actual free space and database growth.

| Data | Retention |
|---|---|
| Payments, closed wash sessions, cash events, mode usage, card ledger, completed Click intents | 12 calendar months |
| System events and configuration history | 1 calendar month |
| Technical logs from Docker and Linux | 1 calendar month, shared journal budget 256 MB; older logs can expire earlier at the size limit |
| Card balances and unclaimed recovery credit | No age-based deletion |
| Open sessions, unresolved payments and their financial trail | Preserved until resolved |

`app/retention.py` runs hourly outside the wash control lock. Deletes are bounded
in batches of 1000, with short lock/statement timeouts and a per-run work budget.
Remaining batches wait for the next run. Failure is visible in Admin; it does not
silently switch to a shorter financial retention period. The legacy blanket
90-day cleanup in wash_logic is disabled. Pause, pricing, trigger and WEB STOP
rules were not changed.

An unclaimed recovery-credit row protects its parent session and all associated
financial rows, avoiding the former `ON DELETE CASCADE` risk. A session with recent
child rows is retained. Uncredited paid Click transactions and pending payments
are retained even after a year. Card records and their current balances are never
part of cleanup. The card ledger itself follows the one-year policy.

PostgreSQL autovacuum reuses space freed by DELETE; a table file need not immediately
shrink on disk. No blocking VACUUM FULL or database reset is run.

## Technical logs

Install using `sudo sh /opt/sammoy/sammoy2/deploy/install-log-retention.sh`.
The Compose services use the journald driver. A daily systemd timer rotates journals
and vacuums them using the preceding calendar-month date, and the 256 MB size cap.
The journald fallback age is 32 days; the daily task applies the calendar cutoff.
The same task prunes only unused Docker build cache older than a calendar month.
It never prunes images, containers, volumes, financial backups or UI uploads.
Successful HTTP polling access logs are disabled; errors and service messages remain.

Driver and quota references: [Docker journald](https://docs.docker.com/engine/logging/drivers/journald/)
and [systemd journal quotas](https://www.freedesktop.org/software/systemd/man/252/journald.conf.html).

## Admin monitoring

Maintenance displays database size, total/free disk, event count, retention periods,
last cleanup result and protected recovery credit. Warning: free space below 10%
or 2 GiB. Critical: below 5% or 1 GiB. Financial retention is never shortened
because a warning is triggered.

## Verification

44 wash-engine tests, six disposable PostgreSQL integration tests, eleven host
network/log tests and all four browser suites passed. The integration database has
its own Docker container/network and never uses the live station ledger. Tests cover
calendar cutoffs, balances, unclaimed-credit protection, open sessions, unresolved
Click payments, recent financial children and Click pagination.

Real relay activation and real network changes were not performed. USB–RS485 is
still disconnected, as confirmed by the user; io-helper deployment awaits its return.

Deployment verification: all eight financial-table row counts and SHA256 checksums
matched before and after deployment. Unclaimed credit remains 1744 sum. The first
background cleanup completed successfully; no current financial records were old
enough for deletion. Database size: approximately 9 MB. All five Compose service
definitions and containers use journald; io-helper is prepared but not started
until USB–RS485 is reconnected. The other four services are healthy. The journal
was reduced from roughly 1.5 GB to 160 MB and the daily timer is enabled.
