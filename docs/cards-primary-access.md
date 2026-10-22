# VIP and card management authority

VIP profile edits, VIP registration/removal and customer metadata changes belong
to the current shared-wallet primary. Existing registry mutation functions call
`authority(cfg).require_primary()` before opening storage, independently of UI.
Standby and ordinary posts read the authoritative registry over signed RPC.

Owner's cards page reads `/api/owner/wallet` and defaults to no editing until
configuration is available. It displays the current primary number and a safe
StationLink to its cards page. Secondary users can view VIP and monetary cards;
mutation controls are disabled and local migration tabs are not offered there.
The original migration service APIs/protocol were not modified by this UI change.
Customer view also respects its server-side `can_edit` flag.

The page refreshes role configuration every ten seconds and rechecks authority
before VIP saves/removal. A standalone controller with shared wallet disabled
continues managing its own local cards. No post number is hardcoded as primary.

Verification: UI fixtures for standby 2/primary 1, ordinary 3/primary 1 and promoted
primary 2; profiles/cards read without writes. Backend test exercises all VIP
mutation functions plus customer mutation on nonprimary roles and asserts no
storage access. Deployed only to second post; backend and first post unchanged.
