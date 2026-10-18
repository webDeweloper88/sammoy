# Shared site wallet and VIP — implementation plan

Status: этапы ядра, репликации, адаптера поста, общего VIP, Click, Telegram, установщика и Owner реализованы. Функция по умолчанию выключена; подключение реальной пары и аппаратная приёмка остаются обязательными. [Состояние, проверки и порядок подключения](shared-wallet-development.md).

## Исходное поведение до общего кошелька

Customer-card money is in local PostgreSQL, not physically written to NFC cards. UID identifies a local record. A funded post returns its credit to a customer card; an empty post loads its card balance. Returning credit closes the local wash session, so reloading can create a session with a new free-pause allowance. Existing card registry and VIP usage counters are local. Site discovery and Telegram aggregation do not provide a transactional wallet or replicated authority.

## Agreed target

### Roles and installation

- New site installation defaults to post 1 as the wallet/Telegram primary.
- Installer explicitly chooses one standby post, e.g. post 7. Post number and service role are separate properties.
- Owner manually promotes the standby after checks and explicit confirmation. Confirmation alone does not fence the previous primary or prove replication completeness.
- A recovered former primary never automatically resumes authority. It synchronizes from the current primary and becomes standby.
- Owner may keep the promoted primary indefinitely or deliberately switch back after synchronization.
- Replication direction always follows the current primary.

### Customer wallet and visit

- One site-scoped wallet per customer card UID; usable at all authorized posts in the same site.
- One visit can span multiple local post sessions. Each visit has one shared free-pause budget under existing engine configuration.
- Card return/reload, switching posts, program changes, additional funding and reboot do not renew an open visit's budget.
- Owner configures the visit timeout centrally; default 30 minutes.
- Timeout starts when funds are returned and no active post assignment remains. It does not end a running/funded post session.
- Reload within the timeout continues the visit and its remaining pause allowance. Reload after expiry starts a new visit; wallet funds remain preserved.
- Saving funds ends financial use of that post. Stored wallet funds do not accrue paid-pause charges.
- Example: post 2 returns 35,000; next day post 7 loads 35,000 and starts a new visit.
- One card may fund only one active post at a time. Do not silently merge another customer's wallet into an occupied funded post.
- Wallet return does not prove that a vehicle physically vacated a bay. Occupancy enforcement is outside this financial feature.

### Replication and outages

- Normal operation: wallet/VIP operations are acknowledged only after durable recording on both primary and standby. Exact durability, acknowledgment and recovery protocol is an implementation requirement, not provided by a simple database copy.
- With primary unavailable: no new customer-wallet loads or VIP authorizations. Already funded/authorized sessions may continue locally under their existing limits; cash operation remains available.
- Unconfirmed wallet returns must not show success. Funds stay assigned to the post unless durable transfer reconciliation proves otherwise.
- With standby unavailable: new shared financial/VIP authorizations stop under normal durability rules.
- Owner may explicitly enable single-authority operation after a safe manual promotion. The UI must explain that new operations then have only one durable server copy until replication recovers.
- Safe promotion requires verified replication completeness and fencing of the old authority. If either cannot be established, block ordinary promotion and require reconciliation; never silently spend an outdated wallet copy.
- Recovered nodes reconcile before service; no automatic promotion or independent writes.
- Telegram reports are sent only by the current primary. Preserve reporting state across promotion and avoid duplicate scheduled sends where possible; ambiguous external send outcomes must be handled explicitly.

### VIP registry

- Common site-scoped registry: UID, type, enabled/blocked status, profile, expiry, permitted programs and usage limits.
- Owner manages cards centrally; Admin diagnoses connectivity/replication. Permissions stay enforced on the server.
- A new VIP session requires primary authorization, recorded under normal replication rules.
- One active post per VIP card. Daily usage limits apply across all posts.
- Tap repetition, migration to another post and reboot do not renew existing visit allowances or duplicate an authorization.
- An already authorized VIP session may finish within its persisted grant while authority is offline; local results synchronize on recovery.
- VIP time does not become customer-wallet money. Keep existing VIP termination/burning semantics unless a separately agreed change is needed.
- Migrate local cards after conflict review. Same UID with incompatible type, profile or blocking status must not be resolved by automatically choosing the most permissive record.

### Mixed monetary funding — confirmed scope

- A paid customer session may combine cash, ordinary NFC wallet credit and confirmed Click/other integrated online-provider payments in one spendable post balance.
- Only providers actually integrated and enabled are offered. This scope does not itself add a new payment provider.
- Preserve source/provider/payment ID in the ledger for each credit. Count each successful payment once; pending, failed or cancelled payments do not add credit.
- Example: wallet 35,000 + cash 10,000 + confirmed Click 20,000 = post credit 65,000. If 12,000 is spent, 53,000 remains transferable to the associated customer wallet.
- Funding does not replenish the current visit's free-pause allowance. Card ownership, active post assignment and transfer reconciliation still apply.
- VIP grants remain separate from monetary credit; mixing money with an active VIP grant is not part of this scope.
- Late online-payment completion must be bound to its original intent/session, never credited to the next customer on the same post. Decide the destination after wallet return/session close (associated wallet where valid, otherwise a recoverable payment credit) before implementation. Include completion-versus-return races and duplicate callbacks in acceptance tests.

## Исходный план и условия приёмки

Программные этапы текущего объёма выполнены; конкретные результаты перечислены в [статусе разработки](shared-wallet-development.md). Перенос старых локальных данных требует отдельной сверки; аппаратная приёмка из пункта 15 ещё предстоит.

1. Inspect current install, site authentication/discovery, database migrations, reports and card/session lifecycles. Record existing invariants and local balances without changing them.
2. Finalize protocol and rules: fencing/rejoin mechanism, promotion completeness evidence, synchronous replication or equivalent durable journal, standalone-mode recovery, mixed cash/card/online-payment ownership and late payment routing, and VIP visit/grant counting.
3. Add site role configuration: initial primary and chosen standby, current primary identity and authority generation, visit timeout default 30 minutes. Define central config distribution and timeout-change behavior for existing visits.
4. Define wallet, shared VIP, visit, post-assignment, transfer and replication schemas. Use unique operation IDs, site scope, row locking/serialization, expiry and immutable audit records.
5. Implement authenticated load/return/authorize/status APIs. Enforce one active card assignment, duplicate-request safety, old-authority rejection and server-side authorization.
6. Implement durable replication, catch-up, integrity checks and crash-safe promotion/rejoin. Demonstrate that a confirmed operation is available after primary failure and that competing authorities cannot both spend funds.
7. Implement engine transfer recovery: prepare, stop outputs when returning, settle exact remainder, commit/acknowledge, reconcile uncertain outcomes. Avoid separate unrecoverable debit/credit commits and never invent local fallback credit.
8. Move free-pause accounting to shared visits while retaining the existing paid-pause tariff, physical trigger/reset interlock, power recovery and output safety. Persist consumption/grant identifiers across restarts and transfers.
9. Integrate VIP authorization and site-wide limits, grant recovery and local usage reporting. Decide and test the precise boundary between continuing an existing VIP grant and creating a new use.
10. Move Telegram leadership and reporting state to the current authority. Verify promotion, rejoin and duplicate-send handling.
11. Add Owner settings for visit timeout, shared card/VIP management and controlled role switching with confirmation. Add Admin replication status, connectivity, journal and pending-transfer diagnostics; avoid exposing secrets.
12. Add customer UI: actual loaded/saved amounts, free/paid pause, card already assigned, wallet unavailable, transfer pending/recovered. Show success only after confirmed accounting.
13. Inventory/migrate existing local records with backups and reconciliation. Flag UID conflicts, prevent duplicate balances and preserve recovery credits and existing financial history.
14. Test: post 2 -> wallet 35,000 -> post 7; repeated-tap free-pause exploit; 30-minute boundary and configured timeout; cross-post daily VIP limit; simultaneous loads; duplicate requests; network partitions; failure at each transfer stage; standby outage; promotion/rejoin; reboot; mixed cash/NFC/Click funding; late payment completion after wallet return; duplicate provider callbacks; payment completion racing with return; wrong-site requests; financial-total conservation; Telegram leadership.
15. Commission with real hardware and at least two posts, review financial reconciliation and outage behavior, then roll out. Mark production-ready only after these acceptance gates pass.

## Решения, принятые при реализации

- Физическое отключение прежнего главного выполняет Owner; потеря heartbeat не доказывает отключение. Без этого подтверждения повышение запрещено.
- Готовность резерва фиксируется после сверки полного журнала. Каждая последующая подтверждённая операция записана на обоих узлах. Неизвестные исходы повторяются с исходным ID.
- Старый главный возвращается через подписанное объявление новой роли, удаление только неподтверждённых orphan-предложений, догрузку и сверку digest. Разошедшиеся подтверждённые операции блокируют восстановление.
- Поздний Click связан с исходной сессией/картой; при отсутствии доказанной карты деньги доступны Owner как отдельный остаток для восстановления.
- VIP продолжает существующий допуск в пределах визита без нового дневного использования. Деньги и VIP не смешиваются.
- Таймаут Owner: 1–1440 минут, по умолчанию 30. Настройка не обновляет уже открытый визит.
- Пункты переноса старых локальных данных и аппаратной приёмки требуют конкретной установленной мойки. Автоматического переноса конфликтующих карт нет.
