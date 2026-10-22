# Local power controls and factory reset

Implemented on 2026-10-20. Automated tests never reset or power down a working
post. Actual reset acceptance below was explicitly authorized by the owner.

## Controls

The login page has Restart and Shut down. Each opens a warning and asks for
Owner/Admin credentials and the uppercase action word. Authentication uses the
existing rate-limited login. The resulting token is used in memory only, must
be at most 60 seconds old, and is not saved as a browser session.

Admin → Maintenance offers two separate reset buttons:

| Operation | Removed/restored | Preserved |
| --- | --- | --- |
| Reset settings | Local tariffs, pause rules, kiosk appearance/text overrides return to defaults | Financial data, cards/VIP, history, accounts, activation, shared-wallet roles/policy, network, hardware wiring/profile, bill stream and filter, Telegram/Click configuration |
| Full reset | All local financial/customer/VIP data and history, site/activation settings, wallet topology and replica, Telegram data, uploaded kiosk assets | Accounts/passwords, host identity, network, OS/application/images, physical I/O maps, monotonic bill stream/filter and its processed offset |

Shared site bonus/pause policy still takes precedence after a local settings reset.
The full reset invalidates existing login tokens, retains account passwords,
switches the host to `factory-only`, and reopens `/install`. It does not reset
the remote payment/licensing server or erase another post's wallet replica.
It is an application reset, not a secure media erase or an OS reinstall.

## Safety and failure behavior

- Active balance, VIP session, pending card transfer or held runtime cash blocks
  the API request. Reset additionally requires confirmed OFF on all eight relays.
- Full reset requires typing FULL and explicitly acknowledging that other posts
  are off/disconnected and that the old standby will be reinstalled before reuse.
  This is an installer assertion, not automatic proof of physical isolation.
- The root worker stops engine/Telegram, then I/O. Engine shutdown flushes usage
  and requests OFF. A DB guard checks credit/transfers again after writers stop.
- Full reset refuses unsettled Click intents. Cancel/reconcile them first.
- The stopped helper's durable total must match the processed PostgreSQL cursor.
  Unprocessed pulses abort reset. Full reset retains only `total` in those cursor
  records, preventing old banknotes from being replayed after installation.
- Reset SQL is one transaction. Customer uploads and Telegram volume are cleared
  only through fixed container paths. No arbitrary shell, Docker socket mount,
  host-root mount or caller-supplied file path is exposed to the engine.
- On worker failure the stack remains stopped for installer review. No automatic
  destructive retry. Root-only job state: `/var/lib/sammoy2-admin/system-job.json`.
  Review the cause before clearing a failed job; never blindly retry a reset.
- Request UUID deduplication prevents resending the last accepted job. Only one
  job may run. Power actions interrupted by the actual host reboot are recognized
  as completed on the next boot by comparing boot IDs.

Install the host bridge with `sudo ./deploy/install-admin-system.sh`; it listens
on `/run/sammoy2-admin/system.sock` (root-only). Installing the service itself
does not reset or power down the device. The golden-template service installer
enables it for new deployments.

Both administrator units share `/run/sammoy2-admin` and MUST set
`RuntimeDirectoryPreserve=yes`. Otherwise restarting one can unlink the other's
socket and replace the directory still bind-mounted in the engine. This defect
was found and repaired on both posts on 2026-10-20: units were updated, sockets
recreated and engine containers recreated once to replace stale mounts. Actual
restarts of each service on each host preserve the directory inode and both
sockets; `/api/commissioning/network/status` continues returning 200. No network
profiles or IP addresses were changed. Live browser acceptance explicitly checks
that network form controls render without the network-service-unavailable alert.

## Two-post acceptance procedure

1. Save any active cash to a card; complete VIP sessions. Check both posts are idle.
2. Agree explicitly that the shared card money/VIP/history on both replicas will
   be removed. A card UID is not a standalone backup of the shared wallet.
3. Settle/cancel outstanding Click intents. Stop customer access and banknotes.
4. Test settings reset first; verify money/cards/history/activation remain.
5. Isolate the other post, run full reset on the first. Keep its hardware helper
   stopped in factory-only mode; do not rejoin an old wallet authority.
6. Reset the isolated second post as well. No old replica may become primary.
7. Reconnect LAN, run `/install` as a fresh two-device site, select wash/dry-fog,
   activation, primary/standby, Telegram optional. Verify roles and identities.
8. Test restart/shutdown with no customer session, then cold boot. Verify no
   replayed cash, no energized outputs on startup, and correct kiosk launch.

### Actual acceptance on 2026-10-20

Owner explicitly authorized deletion of both working datasets. Both runtime
balances were zero, no sessions/transfers were active, and unsettled Click checks
passed. Settings reset on 10.10.10.8 completed through the authenticated engine
API and host worker. Before/after counts were identical: 139 payments, 7 shared
wallet records (including policy records), 1 VIP profile, 44 wash sessions.

Before full reset, both engines and Telegram services were stopped; all eight
outputs were confirmed OFF on each controller, then both helpers were stopped.
Full reset was submitted to the root bridge on each isolated node. Both jobs
completed. Payments, wallet records, VIP profiles and sessions are zero on both.
Processed NV9 cursor records remain (2 first post, 1 second), preserving the
monotonic input boundary. Accounts remain; old auth tokens were invalidated.
Both `/install` endpoints respond 200 and commissioning state is false.
Live browser checks passed on both IPs: Checks → Activation is available without
I/O, login power buttons render, no JavaScript errors. A direct attempt to finish
commissioning without I/O returned 409 on each device; neither was activated.

Both devices are intentionally in factory-only mode, with hardware services
stopped, until recommissioned. Activation and wallet roles can be configured
before I/O is ready; final completion still requires actual I/O readiness.
After types/inventory are configured, the installer applies
`sudo ./deploy/apply-device-profile.sh`; this now starts a stopped helper safely
with the selected map before verifying OFF and starting the matching engine.
Normal power buttons have automated/API/UI verification; actual host shutdown,
reboot and complete fresh activation of this pair remain to be checked.

## Golden image

Use OS + pinned app/dependencies + offline container images, exported through
the clean golden-template workflow. Do not clone either commissioned working SD.
Keep site data, credentials, Telegram keys and old wallet replicas out of the
image. Git remains the source/version workflow; customer installation must not
depend on downloading/building the application from GitHub.

## Статус операции после принятия команды

Root-agent поддерживает read-only `GET /actions/<request UUID>` через закрытый Unix socket. Backend отдаёт публичную квитанцию `GET /api/system/actions/<UUID>`: только действие и статус, без логина исполнителя или boot ID. Случайный UUID известен запросившему браузеру; это позволяет отслеживать завершение после отзыва авторизации полным сбросом. Новые действия по-прежнему требуют свежего входа и всех подтверждений.

После принятия команды панель приостанавливает диагностические запросы и не воспринимает ожидаемый 502/временную потерю backend как обычную ошибку. Она опрашивает статус без сохранения пароля/JWT и без повторной отправки команды. Только `completed` открывает `/install` после полного сброса или `/login` после остальных операций. `failed`/утрата квитанции требуют проверки установщиком. При выключении остаётся сообщение ожидания остановки. Если backend не восстановился, экран не утверждает, что операция успешно закончилась.

Проверено без реального повторного сброса: семь тестов root-agent, 273 unit-теста backend, браузерный сценарий временных 502 → завершение → автоматический переход. Read-only статус также проверяется по уже завершённым реальным операциям на обоих устройствах.

При сбросе резервного узла ранее настроенный туман теперь запускается по локально сохранённым профилю и инвентарю. Проверка доступности/версии второго узла не блокирует запуск всего API; она остаётся обязательной в типизированных командах кошелька до записи финансового журнала. Неверный локальный профиль или отсутствующая миграция по-прежнему блокируют запуск тумана.


## Экран клиента до завершения установки

Полный сброс оставляет `commissioning_state.complete=false`; после подтверждения завершённой операции экран управления автоматически открывает `/install`. Частичная активация или сохранение ролей не открывают мойку: требуется кнопка завершения установки со всеми существующими проверками.

Nginx проверяет `/api/kiosk/access` перед выдачей `/` и `/wash`. Ненастроенный пост получает HTTP 302 на `/install`; `/wash/` приводится к `/wash`. При недоступном backend открывается `/launch` с ожиданием запуска. Проверка и ответ состояния установки не кешируются. Интерфейс дополнительно проверяет состояние до монтирования клиентского экрана, в том числе при запуске через Vite или закладку. Preview-страницы остаются отдельными демонстрациями без команд оборудования.

До завершения установки backend отклоняет запуск программ и создание новых Click-платежей с HTTP 409. Пауза доступна для остановки оборудования. Чтение диагностики и установка доступны. При обычном сбросе настроек флаг завершения установки сохраняется, повторно проходить активацию не требуется.

Проверено: 276 unit-тестов backend, браузерные проверки перенаправлений и отсутствия запросов клиентского экрана до установки, штатного экрана мойки после установки, перехода после полного сброса. Для приёмки используются текущие состояния обоих постов, без повторного сброса и изменения активации.

Read-only приёмка HTTP Location и реального браузерного перехода: `CHROMIUM_EXECUTABLE=/path/to/chrome node tests/customer-setup-gate-live.mjs <host1> <host2>` из `apps/kiosk-ui`. Проверено на текущих постах: настроенный первый отдаёт `/wash` (200), ненастроенный второй отдаёт настоящий 302 с Location `/install` и no-store, затем открывает мастер. JavaScript для самого HTTP-перенаправления не требуется.
