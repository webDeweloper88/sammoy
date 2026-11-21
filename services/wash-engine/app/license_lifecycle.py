"""Shared lifecycle contract: drain existing credit, never silently discard new money."""
BUSY=('creditSum','activeSessionId','activeMode','armedMode','requestedOutput',
      'walletTransferPending','walletCashHeld','vipRemainingSeconds','powerRecoveryAvailable')

def idle(state):
    return not any(state.get(k) for k in BUSY) and state.get('outputsOffConfirmed') is True


def receipt(state):
    lifecycle=(state.get('license') or {}).get('lifecycle') or {}
    ready=bool(state.get('licenseRetirementPending') and state.get('licenseLocked') and idle(state))
    return {'lifecycle_protocol':2,'lifecycle_ack_revision':lifecycle.get('revision') if ready else None,'lifecycle_idle':ready}
