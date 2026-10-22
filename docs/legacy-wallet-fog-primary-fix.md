# Legacy wash return on a dry-fog primary

A wash post can send a legacy wallet command while the authority is a dry-fog
controller. The execute endpoint previously built its legacy WalletPolicy using
the authority runtime's `tariffs['water']`. Dry fog has no water tariff, causing
KeyError before the coordinator could process the return. The local durable job
and funds remained pending; retrying the card could not resolve it.

Both wallet protocols now use the existing service-based `site_policy`: wash
references come from normalized wash settings and fog references from fog
settings, independently of the authority's current hardware type. An absent or
null shared device policy safely falls back to those service settings.

Verification: signed legacy execute endpoint on a fog authority; legacy return
of 15400 including bonus 1400; null and explicit pause policy; existing 20 typed
wallet tests. No production balances or pending jobs are edited by this fix.
Installation is engine-only on the primary after it has no customer session.
The second post's existing pending job is retained and must resume with the same
operation IDs and card. Do not manually recreate, zero or credit the return.

During investigation, the bill filter separately showed a latched stuck_active
fault after a 352.394 ms active pulse with a 250 ms maximum. The line was idle
and counters unchanged in repeated observations. This is separate from the
wallet KeyError. Do not loosen pulse limits before measuring a complete known
bill sequence; do not insert cash while the acceptance path is faulted.
