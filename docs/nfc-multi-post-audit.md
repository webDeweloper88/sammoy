# Shared wallet/VIP design audit

Review date: 2026-10-07. Design review only; no financial code changes.

Verdict: the customer flow is coherent, but replication/promotion and post transfer recovery remain architectural gates. Do not treat a two-node synchronous copy plus Owner confirmation as a complete safe failover protocol.

## Required additions

1. Explicit transfer states and authority ownership: prepared, funds reserved, post accepted, completed; separate uncertain/reconciliation state. Retry queries operation status rather than repeating credit/debit. Wallet and post must never both offer the same amount for spending.
2. A funded post that disconnects retains ownership of its money, VIP grant and allocated pause budget. Lost heartbeats alone must not release its assignment or grant a second post credit/time. Reassignment requires reconciliation or a proven stop/fence of the old post with persisted accounting.
3. Persist actual remaining free-pause/VIP usage locally before returning/reassigning. Central stale copies must not restore consumed seconds. Authority failover and post-session recovery are separate protocols.
4. Normal synchronous durability must include every spendability-changing wallet/VIP operation, not only balance replication. Explicit proof of fencing and rejoin is needed on promotion; role generations alone cannot revoke a disconnected writer that keeps serving clients.
5. Two-node operation tradeoff: loss of either node blocks new replicated transactions in normal mode. Owner may permit single-node operation only after fencing/reconciliation, acknowledging loss of a second durable copy. A second failure then needs recovery, not invented continuity.
6. Late online payment: immutable intent/session identity; credit associated wallet after original session closure only if ownership is valid, otherwise retain a recoverable credit for operator resolution. Never credit the next customer. Confirm with provider status and deduplicate transaction/callback IDs.
7. Revenue accounting: cash/online payments are income once; card loads and wallet returns are internal transfers and must not inflate Owner/Telegram revenue. Preserve original funding source and allow financial-total reconciliation across every post and wallet.
8. Separate replicated operational state from backups. Keep versioned recovery copies independent of replication; accidental deletion/corruption can otherwise propagate to standby. Active wallet balances and unresolved transfers must not be deleted by log retention.
9. Clock/config: use authority time for visit boundaries, monotonic runtime accounting locally, and define timeout changes to apply to new visits so existing visits do not unexpectedly reset. Propose Owner timeout bounds 5–120 minutes with default 30, pending agreement.
10. Privilege/site scope: validate registered posts and site credentials on wallet/VIP APIs; owner/admin permissions server-side. A UID is a lookup key, not authority to edit money or profiles.

## Simplify or exclude from first release

- Keep agreed manual promotion; no automatic promotion or automatic return to post 1.
- No offline fallback spending from cached wallet/VIP balances; no timeout-based automatic release of a disconnected funded post.
- No mixing VIP grants and monetary funding in a single session.
- No implicit conversion of VIP seconds to customer wallet money.
- No arbitrary cross-card transfers during a funded session; keep one associated customer card.
- Add future online providers separately; include existing confirmed Click funding now.
- Keep vehicle occupancy enforcement outside this financial project.

## Clarifications before coding

- VIP transfer: proposed same-visit continuation of an existing grant with its remaining allowance; this changes existing burn-on-end behavior and is not yet a finalized implementation rule. Define what grant units mean under differing tariffs/programs; do not promise identical wall-clock time for all programs.
- Whether cash-only sessions can bind an existing funded customer wallet: recommend no silent wallet load. First use may bind/save the cash remainder to that card under an explicit save action, preserving existing wallet credit rather than replacing it.
- Initial migration: same UID on separate posts may represent duplicate records or separate real balances. Do not blindly sum or overwrite; reconcile ledger provenance and Owner-reviewed conflicts.
- Telegram leadership does not require synchronous persistence for each report. Keep wallet processing independent of Telegram delivery failures; external ambiguous delivery cannot guarantee exactly-once messages.

## Recommended implementation gates

A. Decide/test authority replication, fencing and rejoin, then crash-safe post-to-wallet transfers.
B. Integrate visits/free pause and mixed cash/NFC/Click funding with accounting reconciliation.
C. Add shared VIP with an approved grant-transfer policy.
D. Add installer/Owner/Admin flows and Telegram leadership, migration and physical commissioning.

Acceptance must cover network partitions and crashes at every transition, concurrent card requests, stale role owners, late payments, repeat taps, existing money recovery, revenue not double-counted, and conservation of monetary and time grants.
