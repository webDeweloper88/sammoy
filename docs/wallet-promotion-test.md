# Manual standby promotion test after reset

An unreachable primary is a connectivity result, not proof that the standby has
an authoritative copy. Promotion requires the existing server-side
`standby_ready` proof flag for the current configuration, physical fencing and
explicit acknowledgement of single-copy operation. Never set the proof flag
manually or bypass the server guard.

After resetting/reinstalling standby post 2:

1. Bring primary post 1 back online; both posts must be on the same site, with
   matching roles and keys. Finish setup on the standby.
2. On primary Owner → Wallet, select Synchronize and verify and wait for success.
   If it fails, resolve the diagnostic error rather than proceeding.
3. On standby, refresh wallet status. The copy must now be verified.
4. Physically fence the old primary before confirming promotion. Connectivity
   loss alone does not demonstrate fencing.
5. Check both acknowledgements and type `PROMOTE POST 2`; only then promote.

The standby UI now explains a missing synchronization proof next to the disabled
button. The ready/unready UI test simulates an offline primary: the same checked
boxes and phrase enable only the verified copy. No promotion or synchronization
is performed by this test or by the UI explanation deployment.
