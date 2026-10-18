> **Текущий статус всей системы (16 октября 2026):**
> [что готово, где остановились и что дальше](project-status-2026-10-16.md).
> Нижние handoff-разделы сохранены исторически. Периферия уже подключена;
> аппаратная приёмка продолжается, а не начинается разработка Owner/UI заново.

> Актуальный аудит от 2026-10-07: [сравнение и подтверждённые проблемы](sammoy2-audit-2026-10-07.md), [план реализации](implementation-roadmap.md). Ниже сохранён исторический handoff. Указание watchdog в YAML не подтверждает его реализацию в текущем Radxa io-helper; см. A-01/A-02. Актуальная ориентация интерфейса — 1080×1920.

# SAMMOY 2.0 — Codex Handoff / Project README

> **Purpose of this file**
>
> Read this file first before changing code.
> It describes the current architecture, the decisions already made, the hardware mapping,
> the wash-engine state machine, the tests already completed, known issues, and the next tasks.
>
> **Do not redesign settled parts unless explicitly requested.**
> Prefer small, reversible changes with backups and verification after each step.

---

## 1. Project

Project: **SAMMOY 2.0**  
Use case: self-service car wash kiosk/controller.

Current project root on Radxa:

```bash
/opt/sammoy/sammoy2
```

Old working source kept for reference:

```bash
/opt/sammoy/old-project
```

The old `wash-engine` was migrated into the current Radxa project.  
The newer Radxa-specific `io-helper` was retained.

---

## 2. Current architecture

```text
NV9 / PC817 test pulse
    |
    v
Radxa Cubie A7A
GPIO11
/dev/gpiochip0 line 33
    |
    v
sammoy2-io-helper
host 127.0.0.1:8080
container :8080
Modbus RTU /dev/ttyUSB0
slave = 1
    |
    v
8DI / 8DO isolated I/O board
    |
    +--> water
    +--> osmos
    +--> nano
    +--> foam
    +--> wax
    +--> chem
    +--> vacuum
    +--> air

sammoy2-wash-engine
host 127.0.0.1:8090
container :8080

sammoy2-postgres
host 127.0.0.1:5432
```

---

## 3. Hardware facts

### Radxa

Current SBC:

- Radxa Cubie A7A
- Debian Bullseye 11

### NV9 bill acceptor

Current production pulse input:

```text
GPIO11
gpiochip0 line 33
```

Tested with:

```bash
sudo gpiomon -f -n 10 -F '%s.%09n FALLING' gpiochip0 33
```

This input was stable.

Current money mapping:

```text
1000 sum = 1 pulse
```

Future:

```text
5000 sum = 5 pulses
```

Real NV9 is not yet connected in final production test.
PC817 is currently used to simulate pulses.

### Total Stop / trigger

DI3 is used as physical gun trigger / Total Stop.

Important:

```text
active_low
raw DI3 = 0  -> total_stop = true
raw DI3 = 1  -> total_stop = false
```

Example `/io`:

```json
{
  "inputs": {
    "total_stop": true
  },
  "raw_inputs": [1, 1, 0, 1, 1, 1, 1, 1]
}
```

### Outputs

The current 8 outputs are:

```text
water
osmos
nano
foam
wax
chem
vacuum
air
```

---

## 4. io-helper API

Base:

```text
http://127.0.0.1:8080
```

Endpoints:

```text
GET  /health
GET  /io
POST /outputs/{name}
```

Example:

```bash
curl -s http://127.0.0.1:8080/io | python3 -m json.tool
```

Output command:

```bash
curl -s -X POST \
  http://127.0.0.1:8080/outputs/water \
  -H 'Content-Type: application/json' \
  -d '{"on":true}'
```

Safety already implemented in io-helper:

```text
startup_all_off
shutdown_all_off
readback_after_write
controller watchdog = 2 sec
```

---

## 5. wash-engine API

Base:

```text
http://127.0.0.1:8090
```

Useful endpoints:

```text
GET  /health
GET  /api/wash/state
POST /api/wash/mode
POST /api/owner/wash/parameters
GET  /api/owner/wash/parameters
POST /api/auth/login
```

Select WATER:

```bash
curl -s -X POST \
  http://127.0.0.1:8090/api/wash/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"water"}' \
| python3 -m json.tool
```

WEB PAUSE:

```bash
curl -s -X POST \
  http://127.0.0.1:8090/api/wash/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"pause"}' \
| python3 -m json.tool
```

Useful state check:

```bash
curl -s http://127.0.0.1:8090/api/wash/state \
| python3 -m json.tool \
| grep -E \
'"phase"|"creditSum"|"selectedMode"|"armedMode"|"activeMode"|"requestedOutput"|"totalStopActive"|"freePauseRemaining"|"pauseState"|"triggerGraceRemaining"|"resumeRequiresTriggerReset"|"triggerResetConfirmRemaining"'
```

Note:

`/api/wash/state` currently may show `totalStopActive` twice in grep output because the response contains both:

```text
state.totalStopActive
simulation.totalStopActive
```

The first one is the real runtime state.

---

## 6. Current wash parameters

Current important defaults:

```json
{
  "billPulseSum": 1000,
  "coinPulseSum": 1000,
  "freePauseSeconds": 60,
  "triggerGraceSeconds": 1,
  "triggerResetConfirmSeconds": 0.5,
  "powerRecoverySeconds": 600,
  "requireTotalStopTrigger": true,
  "paidPause": {
    "enabled": true,
    "amountSum": 1000,
    "durationSeconds": 120,
    "sumPerMinute": 500
  }
}
```

### Important business meaning

#### `freePauseSeconds`

```text
60 sec shared free-pause budget PER SESSION
```

It is NOT replenished by:

- switching programs
- pressing PAUSE multiple times
- releasing trigger repeatedly

#### `triggerGraceSeconds`

```text
1 sec
```

When physical trigger changes ON -> OFF:

1. output goes OFF immediately
2. 1 second trigger grace starts
3. after grace, shared free pause is consumed
4. after free pause is exhausted, paid pause starts

#### `triggerResetConfirmSeconds`

```text
0.5 sec
```

After WEB PAUSE was pressed while trigger was physically held ON, the customer must actually release the trigger.

The trigger must remain continuously OFF for at least 0.5 sec before restart interlock is cleared.

This protects against contact bounce / short DI glitches.

#### `paidPause`

```text
1000 sum / 120 sec
= 500 sum/min
= ~8.33 sum/sec
```

#### `requireTotalStopTrigger`

Default:

```text
true
```

When `true`:

- DI3 physical trigger participates in output permission

When `false`:

- DI3 remains visible in diagnostics
- DI3 must NOT affect output permission

This winter/bypass mode is implemented in backend but final UI-based test is still pending.

---

## 7. Current tariffs

Current old-derived tariffs are still:

```text
water:
1000 / 40 sec
= 1500 sum/min

foam:
1000 / 20 sec
= 3000 sum/min

chem:
1000 / 20 sec
= 3000 sum/min

nano:
1000 / 20 sec
= 3000 sum/min

wax:
1000 / 20 sec
= 3000 sum/min

vacuum:
1000 / 20 sec
= 3000 sum/min

air:
1000 / 20 sec
= 3000 sum/min

osmos:
1000 / 20 sec
= 3000 sum/min
```

A newer intended tariff model was discussed:

```text
water/osmos/vacuum/air:
1500 / 60 sec

foam/chem/nano/wax:
1500 / 40 sec
```

**Do NOT change tariffs until explicitly confirmed.**

---

## 8. Wash state machine — intended behavior

### Active program

Example WATER:

```text
selectedMode = water
armedMode = water
activeMode = water
requestedOutput = water
phase = active
```

Physical output:

```text
water = true
```

Balance is charged at WATER tariff.

---

## 9. Physical trigger release behavior

When WATER is active and trigger is released:

```text
DO OFF immediately
```

Then:

```text
phase = trigger_grace
triggerGraceRemaining = 1
```

Balance is NOT charged during trigger grace.

After grace:

If free pause remains:

```text
phase = pause_free
pauseState = free
```

If free pause is exhausted:

```text
phase = pause_paid
pauseState = paid
```

---

## 10. Shared free pause

The free-pause budget is initialized once for a funded session.

Runtime fields:

```text
freePauseRemaining
_pauseBudgetFloat
_pauseBudgetInitialized
```

Important rule:

```text
Mode switching must NEVER replenish free pause.
Repeated PAUSE must NEVER replenish free pause.
Trigger release must NEVER create a new free-pause budget.
```

---

## 11. Paid pause

After shared free pause reaches zero:

```text
phase = pause_paid
pauseState = paid
```

Current tariff:

```text
1000 / 120 sec
```

Verified manually.

Observed example:

```text
405 -> 383 sum
~2.6 sec
```

Expected:

```text
8.33 sum/sec * 2.6 sec ~= 21.7 sum
```

This matched.

---

## 12. WEB PAUSE behavior

WEB PAUSE has priority over physical trigger.

If customer is washing and physical trigger is held ON:

```text
WATER active
trigger = ON
```

Then WEB PAUSE:

```text
selectedMode = pause
armedMode = water
activeMode = null
requestedOutput = null
water DO = false
resumeRequiresTriggerReset = true
```

The output must turn OFF immediately.

---

## 13. Restart interlock after WEB PAUSE

Critical safety/business rule:

If WEB PAUSE is pressed while trigger is physically held ON, then selecting WATER again must NOT start the output while the trigger is still held.

Expected:

```text
selectedMode = water
armedMode = water
activeMode = null
requestedOutput = null
totalStopActive = true
resumeRequiresTriggerReset = true
phase = trigger_reset_pause_free
```

Physical output:

```text
water = false
```

This has been manually tested successfully.

---

## 14. Trigger reset debounce

Initial implementation cleared:

```text
resumeRequiresTriggerReset
```

on one single OFF sample.

That was unsafe because a brief DI glitch/bounce could clear the interlock.

Current implementation uses:

```text
triggerResetConfirmSeconds = 0.5
```

State fields:

```text
resumeRequiresTriggerReset
_triggerResetOffFloat
triggerResetConfirmRemaining
```

Behavior:

```text
WEB PAUSE while trigger ON
-> resumeRequiresTriggerReset = true

brief OFF < 0.5 sec
-> interlock remains true

continuous OFF >= 0.5 sec
-> interlock clears

new ON
-> program can run
```

There is also a per-tick flag:

```text
trigger_reset_cleared_this_tick
```

to avoid consuming the same `elapsed` twice in trigger grace accounting.

---

## 15. Power recovery

Current Owner default:

```text
powerRecoverySeconds = 600
```

Behavior already implemented:

### Outage <= timeout

Recover same session:

```text
phase = interrupted_resume
credit restored
same activeSessionId
powerRecoveryAvailable = true
```

Safety:

```text
selectedMode = pause
armedMode = null
activeMode = null
requestedOutput = null
```

No wash output is automatically resumed after reboot.

### Outage > timeout

Old/stale session is closed.

Remaining balance is preserved in:

```text
recovery_credits
```

with:

```text
status = unclaimed
```

---

## 16. Free-pause persistence across power recovery

This was recently added.

Problem that was fixed:

Before the patch, recovery did:

```text
freePauseRemaining = 0
_pauseBudgetFloat = 0
```

and did not restore:

```text
_pauseBudgetInitialized
```

Therefore `_ensure_pause_budget_locked()` could later grant another full 60 sec after reboot.

### Current solution

No new DB column was added.

Existing:

```text
wash_sessions.metadata JSONB
```

is used.

Heartbeat now persists:

```json
{
  "pause_budget_initialized": true,
  "free_pause_remaining": 43.8
}
```

Heartbeat updates:

```text
final_credit_sum
runtime_seen_at
status
metadata.pause_budget_initialized
metadata.free_pause_remaining
```

Recovery SELECT now reads:

```text
metadata
```

Recovery restores:

```text
_pauseBudgetInitialized
_pauseBudgetFloat
freePauseRemaining = ceil(_pauseBudgetFloat)
```

Safety limit:

```text
restored free pause <= current freePauseSeconds
```

Legacy sessions without these keys are treated fail-safe:

```text
_pauseBudgetInitialized = true
_pauseBudgetFloat = 0
```

This prevents old sessions from receiving a new free 60 sec after reboot.

### Manual test result

Before restart:

```text
session id = 6
pause_budget_initialized = true
free_pause_remaining = 2.42 sec
```

After restart:

```text
phase = interrupted_resume
activeSessionId = 6
powerRecoveryAvailable = true
freePauseRemaining = 0
```

This is expected because the remaining ~2.42 sec expired before the process fully stopped and paid pause started.

Important result:

```text
reboot did NOT grant a new 60 sec free-pause budget
```

Full UI-driven test with a larger remaining balance should be repeated later.

---

## 17. Database

PostgreSQL container:

```text
sammoy2-postgres
```

Current DB / user:

```text
POSTGRES_DB=rtu_wash
POSTGRES_USER=rtu_wash
```

Do not hardcode passwords/secrets into source code.

Useful query:

```bash
sudo docker exec -i sammoy2-postgres \
  psql -U rtu_wash -d rtu_wash \
  -c "
SELECT
    id,
    status,
    final_credit_sum,
    runtime_seen_at,
    metadata->>'pause_budget_initialized' AS pause_initialized,
    metadata->>'free_pause_remaining' AS free_pause_remaining
FROM wash_sessions
WHERE status IN ('running','started','open')
ORDER BY id DESC
LIMIT 3;
"
```

Important tables:

```text
app_settings
auth_users
wash_sessions
payments
cash_events
mode_usage
system_events
recovery_credits
rfid_cards
rfid_card_ledger
```

---

## 18. Owner authentication

Owner APIs require:

```text
Authorization: Bearer <token>
```

Login endpoint:

```text
POST /api/auth/login
```

Body:

```json
{
  "login": "...",
  "password": "..."
}
```

Owner parameter endpoints:

```text
GET  /api/owner/wash/parameters
POST /api/owner/wash/parameters
```

Current default owner account may have:

```text
must_change_password = true
```

In that case Owner API returns:

```text
Password change required
```

Do not bypass this in backend just for tests.

The user explicitly decided:

```text
Test requireTotalStopTrigger=false later through finished Owner UI.
```

---

## 19. Owner UI — required parameters

Owner UI should expose at minimum:

```text
freePauseSeconds
triggerGraceSeconds
triggerResetConfirmSeconds
paidPause.enabled
paidPause.amountSum
paidPause.durationSeconds
requireTotalStopTrigger
powerRecoverySeconds
```

Tariffs should also be configurable there.

Do not hide the current values.

Changes should update runtime dynamically through existing:

```text
wash_runtime.save_parameters(...)
```

---

## 20. Current test status

### Tested successfully

- NV9/PC817 pulse counting path
- GPIO11 pulse input
- Modbus I/O
- WATER output
- WATER tariff charging
- physical Total Stop / trigger
- immediate output OFF on trigger release
- trigger grace
- shared free pause
- paid pause
- paid-pause charging rate
- WEB PAUSE
- WEB PAUSE priority over physical trigger
- restart interlock
- 0.5 sec trigger reset confirmation
- power recovery
- recovery does not auto-resume output
- free-pause persistence metadata write
- reboot does not grant a fresh free-pause allowance

### Not fully tested yet

- `requireTotalStopTrigger=false` via UI
- all 8 wash programs under final UI
- full free-pause recovery with nonzero remaining value, UI-driven
- all DB accounting paths after final UI
- all session reset/close paths after final UI

---

## 21. Known TODOs in wash-engine

### A. Audit all reset paths

Search all places that reset:

```text
_pauseBudgetFloat
_pauseBudgetInitialized
pauseState
_triggerGraceFloat
triggerGraceRemaining
resumeRequiresTriggerReset
_triggerResetOffFloat
triggerResetConfirmRemaining
```

Make sure all true session-ending/reset flows clear the whole set consistently.

Especially inspect:

- RFID/card flows
- VIP flows
- license lock/unlock flows
- manual stop
- no_credit
- saved_to_customer_card
- recovery timeout

Do not blindly reset these fields during an active recovered session.

---

### B. WEB STOP business rule is not finalized

Current `stop_wash()` behavior:

```text
creditSum = 0
close session
operator_stop
```

For VIP:

```text
vip_remaining_burned
```

But final product rule for leftover cash balance is not yet decided.

Do not redesign this without explicit user decision.

Potential options later:

```text
burn
save to card
recovery credit
confirmation dialog
```

---

### C. Admin hardware endpoints

Some old Admin API code still uses old paths such as:

```text
/do/{name}/{state}
/do/all-off
```

Current io-helper API is:

```text
POST /outputs/{name}
{"on": true|false}
```

These old Admin endpoints must be adapted before final production.

---

### D. `paidPause.enabled=false`

Current behavior may allow:

```text
pause_free_exhausted
```

with no charge and output OFF.

This could become indefinite unpaid waiting.

Business rule is not yet decided.

Do not change without explicit decision.

---

### E. Full nonzero free-pause recovery test

Repeat later through finished UI:

```text
new session
60 sec free pause
consume ~15 sec
save ~45 sec in DB
restart wash-engine
verify ~45 sec restored
```

Do not rely only on rounded display; compare DB float and API ceil value.

---

## 22. Source backups currently present

Several backup files exist, including examples such as:

```text
wash_logic.py.bak-radxa
config.py.bak-radxa
wash_logic.py.bak-power-recovery
main.py.bak-power-recovery
wash_logic.py.bak-pause-v2
wash_logic.py.bak-pause-stage1
wash_logic.py.bak-pause-stage2
wash_logic.py.bak-pause-stage3
wash_logic.py.bak-trigger-reset-debounce
wash_logic.py.bak-trigger-reset-fix
wash_logic.py.bak-trigger-timing-final
wash_logic.py.bak-pause-persistence
wash_logic.py.bak-pause-persistence-v2
```

Do not commit backup files to Git.

Do not delete them until current implementation is stable and committed.

---

## 23. Build / restart

Syntax check:

```bash
cd /opt/sammoy/sammoy2

python3 -m py_compile \
  services/wash-engine/app/wash_logic.py
```

Build only wash-engine:

```bash
sudo docker compose build wash-engine
```

Recreate only wash-engine:

```bash
sudo docker compose up -d \
  --no-deps \
  --force-recreate \
  wash-engine
```

Restart only:

```bash
sudo docker compose restart wash-engine
```

Status:

```bash
sudo docker compose ps
```

Health:

```bash
curl -s http://127.0.0.1:8090/health \
| python3 -m json.tool
```

---

## 24. Important coding rules for future Codex work

1. **Read this README first.**
2. Do not replace the current state machine with a new architecture.
3. Make small, reversible patches.
4. Before changing a working file, make a backup.
5. Run `py_compile` before rebuild.
6. Inspect the exact modified lines before rebuild.
7. Rebuild only the affected service when possible.
8. Test the physical `/io` state, not only wash-engine API state.
9. Never assume a web state means a relay actually changed.
10. Preserve safety behavior:
    - outputs OFF on startup
    - outputs OFF after restart
    - no automatic restart of a wash program after power recovery
    - WEB PAUSE immediately de-energizes active output
11. Do not grant additional free pause through:
    - mode switching
    - repeated PAUSE
    - reboot
    - power recovery
12. Do not change final tariffs until explicitly confirmed.
13. Do not change WEB STOP money behavior without explicit business decision.
14. Do not hardcode passwords, JWT secrets, DB secrets, or real credentials.
15. Do not commit `.env`, data directories, backup source files, or secrets.

---

## 25. Recommended next development order

Recommended sequence:

```text
1. Build Owner UI wash-parameter page
2. Expose:
   - freePauseSeconds
   - triggerGraceSeconds
   - triggerResetConfirmSeconds
   - paidPause
   - requireTotalStopTrigger
   - powerRecoverySeconds
   - tariffs

3. Test requireTotalStopTrigger=false through UI

4. Repeat full wash state-machine test through UI:
   WATER
   PAUSE
   trigger reset
   grace
   free pause
   paid pause
   recovery

5. Test all 8 modes

6. Audit wash_sessions / mode_usage accounting

7. Audit all reset paths

8. Fix old Admin /do/... endpoints

9. Decide WEB STOP leftover-money rule

10. Real NV9 test

11. PN532 / RFID later

12. Final RTC / cold power-loss test
```

---

## 26. UI project direction

Brand:

```text
Labrixwash
```

Display:

```text
27-inch touch panel, 1920 x 1080 landscape (confirmed by owner)
RU / UZ / EN
```

Main program buttons:

```text
water
foam
air
vacuum
pause
osmos
nano
wax
chem
```

Main order page concept:

```text
Header
-> Сейчас работает
-> Остаток
-> Выбор программы
-> Баланс
-> Footer
```

Idle after approximately:

```text
3 min with zero balance
```

---

## 27. What NOT to redo

Already settled / tested:

```text
Radxa GPIO11 for bill pulse
io-helper on port 8080
wash-engine on port 8090
DI3 physical trigger / total_stop
active_low trigger semantics
8 output names
WEB PAUSE priority
shared 60 sec free pause
1 sec trigger grace
0.5 sec trigger reset confirmation
paid pause 1000 / 120 sec
power recovery <= 600 sec
no automatic output resume after reboot
free-pause state persisted in wash_sessions.metadata
```

Only revisit these when a real test demonstrates a bug or the user explicitly changes the business requirement.

---

## 28. Current overall status

`wash-engine` core logic is approximately **85–90% complete**.

The core runtime and safety logic are working.

Remaining work is mostly:

```text
UI integration
full mode coverage
final business rules
accounting audit
Admin endpoint cleanup
real hardware final tests
```

Do not call the backend "production ready" until those remaining items are closed.

---

## 29. Short context for Codex

If only one paragraph can be read, use this:

> SAMMOY 2.0 is a Radxa Cubie A7A self-service carwash controller. `io-helper` is on port 8080 and controls an 8DI/8DO Modbus board; `wash-engine` is on port 8090. DI3 is an active-low physical gun trigger (`total_stop`). WATER and pause logic are tested. A session has one shared 60 sec free-pause budget, 1 sec trigger grace, 0.5 sec stable-OFF restart confirmation after WEB PAUSE, then paid pause at 1000 sum / 120 sec. WEB PAUSE immediately turns outputs OFF and prevents restart while the trigger remains held. Power recovery restores money/session but never auto-resumes outputs. Free-pause remaining is persisted in `wash_sessions.metadata` so reboot cannot grant a new 60 sec. Current default `requireTotalStopTrigger=true`; bypass=false-mode will be tested later through Owner UI. Do not change tariffs or WEB STOP money behavior without explicit approval. Next priority is Owner UI integration and then full UI-driven regression testing.


## 30. Owner UI and Telegram migration — 2026-09-29

Owner pages now include local/multi-station reports, VIP profiles and cards,
customer-screen settings, Telegram and account, alongside wash parameters.
Light/dark selection persists locally. Touch keyboard remains available on the
1920×1080 landscape panel. `/login` links to the new `/install` activation-code /
signed-response wizard. The customer wash screen and full Admin pages remain
subsequent stages; this does not certify the hardware stack for production.

Current pause rules in THIS README are authoritative. `wash_logic.py` was not
modified for Owner work. Five inherited tests expected legacy pause replenishment
or automatic resume; their expectations now cover the current shared budget,
trigger grace, paid-pause rate and continued outputs-off after WEB PAUSE.
34 wash-engine unit tests pass, including Owner API regressions.

Backend Owner changes:
- optional `include_inactive=true` lists blocked/disabled VIP cards for restoration;
- VIP upsert atomically rejects nonzero card balances instead of erasing money;
- authenticated reporting setup proxy and aggregated station report endpoint;
- background sync of installed site identity to Report API (no wash controls).

See `services/telegram-reports/README-SAMMOY2.md` for deployment and commissioning.
Report API uses a dedicated read-only SQL role and preserves old-project discovery
compatibility. 26 reporting tests pass. UI tests use intercepted writes and cover
touch login/password changes, Owner workflows, themes, partial reports and install.

This board is a NEW installation per the user. Its site identity is not yet set.
Actual multi-post discovery and Telegram message delivery require a real activation
server/code or signed setup response, plus the BotFather token and owner pairing.
Do not invent licence settings, site tokens or station identities to bypass setup.
Do not clear the existing test/client credit during installation work.

Deployment verification for this change: all five Compose services healthy; UI
`/login` and `/install` return 200; unauthenticated Owner reporting endpoints return
401. The real local and aggregated Report API both read seven existing sessions.
The report DB connection reports read-only mode and has no INSERT/UPDATE/DELETE
privileges. After deployment, credit stayed 1744 sum, all eight physical outputs
were OFF, and PN532 stayed online. The existing remaining credit was not reset.

`/install` now prevents UI activation while credit remains. Actual activation is
still pending: the operator must supply the genuine server/code or signed response,
and complete the current session according to the agreed money-handling rules.

## 31. Admin UI — 2026-10-02

Admin now opens `/admin/diagnostics`, with Connection and Maintenance pages.
See [Admin operation and verification](admin.md). Wi-Fi/static IPv4 use the host
NetworkManager service and a 90-second confirmation/rollback checkpoint. Network
settings were not changed during development. Relay tests are finite, confirmed
and blocked by unfinished customer sessions; all-off follows current WEB PAUSE.
`wash_logic.py` remains unchanged (SHA256
`8b05dd9b9d0a8694f0e3f8609393043137af47ea006b2e57c7e251889e5fbecb`).

87 isolated tests and all four browser suites passed. Physical hardware acceptance
remains outstanding: the user confirmed USB–RS485 cannot be connected now,
`/dev/ttyUSB0` is missing, and io-helper is stopped. Do not describe hardware as
ONLINE or production-ready based on UI tests. The customer main screen is still
a separate next stage. On restart the existing timeout policy moved session 8
to recovery_credits: id 1, 1744 sum, unclaimed. Current session balance is 0;
the money remains recorded in the saved-remainders table. No manual money reset
or change to recovery rules was made.

## 32. Admin separation and retention — 2026-10-03

Admin navigation now contains Diagnostics, Connection, License, Click, Maintenance
and Account. Owner business pages and their mutation APIs are Owner-only. A direct
Admin attempt to open an Owner page redirects to Admin diagnostics; API requests
receive 403. Account/password management remains available independently to both.

License details include decisions, binding, expiry, last/next synchronization and
offline grace. Connection shows board/microSD identity and fingerprint. Click has
status filters and cursor pagination. RFID diagnostics retain the last processing
result even when subsequent reader heartbeats arrive.

The agreed storage policy is implemented: financial history 12 calendar months,
events 1 calendar month, bounded monthly technical logs. Card balances and unclaimed
credit do not expire. See [storage policy and deployment](storage.md). The old
90-day deletion is disabled; retention runs independently of the wash loop.
Only retention plumbing and RFID diagnostic fields changed in wash_logic.py;
pause/trigger, tariff and money-handling branches were not modified.

Deployment completed: web UI is available at http://10.10.10.8/login; financial
checksums matched across all eight tables, including the preserved 1744 sum.
The first retention run succeeded. io-helper remains unstarted because the
USB–RS485 adapter is absent; its new image and logging configuration are prepared.

## 33. Customer Screen 2 (portrait)

The customer interface is now available at `/` and `/wash`, with the real 3-minute idle screen integrated. Screen 2 uses real Vue/CSS/SVG components, six main radial programs plus independently configurable air/vacuum below (user-approved layout), UZ/KZ/KY/RU, server-derived time and the existing Click/cash/wash-card workflows. See [wash-screen.md](wash-screen.md) for files, sources of state, palette/sizing, verification and physical commissioning limits. Billing, shared free-pause budget and physical-trigger interlock logic are unchanged by this UI integration.

## 34. Daylight / dark customer appearance

Customer working screen and dialogs support the approved light palette. Owner → Wash screen selects Auto by Tashkent time (default light 08:00–18:00, adjustable) or Manual with a permanent Light/Dark choice. Settings are stored in `kiosk_settings.theme.appearance`; a customer page applies saved changes within its 15-second settings refresh and changes at schedule boundaries without a reload or equipment command. See [wash-screen.md](wash-screen.md).
