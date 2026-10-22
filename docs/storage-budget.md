# Storage on 32 GB and 64 GB devices

Factory reset deletes application data under the existing financial safety checks,
then starts the factory profile and runs disposable storage cleanup. Settings-only
reset retains customer data and does not trigger this cleanup. Cleanup failure
cannot turn a successful reset into a failed destructive operation.

`deploy/storage-maintenance.py` removes regular archive files only from fixed update
cache directories, never follows symlinks, never removes folders or application
volumes. Legacy development transfer archives in `/home/admin/.cache/sammoy-tools`
are included. Daily cleanup retains uploads for 48 hours; full reset removes all
such archives. Python helpers and development runtime directories are retained.
Unused Docker build cache is reduced toward 512 MB (daily: older than 48 hours).
Docker images, containers and volumes are retained, including rollback images.
APT package download cache is cleared. Daily execution uses the existing
`sammoy2-log-retention.timer`; journald is bounded to 256 MB, runtime to 64 MB.
Daily technical logs expire after a calendar month. Financial records and the NV9
monotonic counter are never a storage cleanup target.

The factory installer enables this retention policy. A production image must omit
VS Code Server, Codex caches, source-transfer archives and build tools. Development
usage is not a production disk budget. 32 GB eMMC needs a measured clean-image size
and long-running growth check before release; no promise of unlimited financial
history retention is implied. Archive financial history separately rather than
silently deleting it. Retained release/rollback images need deliberate release
management, not an unattended `docker system prune -a --volumes`.
