# NFC transfer latency — 2026-10-19

The user confirmed inserting an additional 20,000 cash during testing; the
reported 33,000 sum included bonus and was not a false NV9 credit. At the final
pre-acceptance read, both posts are empty and the ordinary card 507EF458 holds
55,000 sum (5,000 bonus); the most recent completed load and return both record
55,000. This release does not reset or alter balances.

## Change

- Reuse bounded HTTP keep-alive pools for signed wallet RPCs and I/O. Pools are
  separate by purpose/timeout; replies, signatures and configuration are not cached.
- Preserve all OFF acknowledgements, operation IDs, replication confirmations,
  durable job stages and financial locks. No automatic POST retry was added.
- Poll the kiosk state every 250 ms instead of 500 ms.
- During a locked wallet operation, serve a detached read-only pending snapshot.
  It retains the last confirmed balance and disables service starts. Show a
  processing message rather than a false connection outage or a premature success.
  After completion/failure, discard the transient snapshot; durable pending jobs
  still use the existing recovery/re-present-card message.

## Evidence

Before transport pooling: median wallet status RPC 48.45 ms (post 1),
50.75 ms (post 2), eight samples each. After first live engine update:
29.75 ms and 30.6 ms respectively. These are RPC timings, not full card timings.
The last pre-update physical return took approximately 3.57 s from RFID processing
start to durable job completion. Physical taps after the final deployment: two load jobs completed in
1,131/1,180 ms; two return jobs in 1,710/1,710 ms. End-to-end return from
lastRfidProcessedAt to durable completion: approximately 2.58 s (previous
3.57 s). Read-only HTTP monitoring observed pending snapshots throughout the
transfer, then confirmed balances, with no state request timeout. The user confirmed that the brief offline banner no longer appears.

Tests: HTTP pool reuse, concurrent creation, transport separation and no POST
replay; pending snapshot with blocked OFF confirmation, detached balances, failure
cleanup and an already-waiting reader. Wallet adapter PostgreSQL integration and
kiosk browser regression passed. No production money is modified by tests.

## Deployment

Final backend and kiosk UI installed on both posts. Both engines healthy,
I/O ready, both local balances zero, no pending local transfer jobs on post 1.
233 unit tests, 15 wallet-adapter PostgreSQL tests and the kiosk browser test
passed. Earlier full integration run: 165 passed, 7 intentionally skipped.

## Second optimization — scoped protocol proofs

One synchronous card operation may reuse authenticated metadata status proofs
for at most two seconds. The scope is ContextVar-isolated and discarded on exit,
including exceptions. Cache keys include site, local/primary/standby posts,
generation, redundancy mode and target address. Each discovery still reads local
configuration. Card inspection and all financial commands remain uncached.
Nested VIP/money adapters share only this short-lived proof scope. Automatic
session-end transfers also get their own scope.

Every updated client execute request includes expected primary and generation;
the receiving primary rejects a mismatch before applying the money command.
Receiver-side protocol checks, journal fencing, replication, OFF acknowledgements,
operation IDs and durable local stages are unchanged. No background money work or
automatic command replay was introduced.

Regression: 238 unit tests passed; PostgreSQL integration 165 passed, 7 skipped.
The three-command client test makes exactly two status RPCs (one per node) while
all three commands and both requested card inspections still execute. Proof expiry,
role/address changes, failure cleanup, nested scopes and receiver epoch rejection
are covered. Engine logs record per-operation RPC counts/durations, without card
IDs, amounts, tokens or card state. Physical acceptance on post 1 after deployment:

- Load: scoped runtime operation 1,504 ms; durable load job 906 ms.
- Return: scoped runtime operation 1,939 ms; durable return job 1,301 ms;
  RFID-processing timestamp to durable completion approximately 2,014 ms.
- Load made two status calls, two inspect calls and two execute calls, reusing
  protocol proofs 12 times. Return made two status calls, two inspect calls and
  three execute calls, reusing proofs 17 times. No execute response was reused.
- Amount 55,000 sum loaded and returned; post balance zero afterwards.

Compared with the first optimization (return approximately 2.58 s), final return
is approximately 2.0 s; the original observed return was approximately 3.57 s.
Measurements are a small bench sample, not a guaranteed latency bound. Network,
peer journal synchronization and storage latency still affect transfer time.
Both post backends updated and healthy; no kiosk/helper restart required.

## Kiosk feedback follow-up

The user reported a repeat-card instruction during the first successful transfer.
The current served UI already distinguishes walletOperationInProgress from a
durable pending transfer. Both physical kiosk browser windows were refreshed
with Ctrl+R to load the current bundle, without restarting the engine or changing
balances. Stale in-memory UI was suspected. After refreshing both kiosk windows, the user
confirmed that the first-tap feedback works correctly.
The browser regression now asserts that an in-progress transfer shows wait text,
contains no re-present-card instruction and disables service starts; an interrupted
pending transfer shows the recovery instruction, which disappears on completion.
The complete kiosk browser regression passed.
