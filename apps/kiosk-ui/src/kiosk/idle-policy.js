export const IDLE_TIMEOUT_MS = 180000
export const STATE_FRESHNESS_MS = 5000
// Missing state must never be interpreted as an empty, available wash bay.
export function canAttract(state, { receivedAt = 0, now = Date.now(), paymentPending = false } = {}) {
  return Boolean(state && receivedAt > 0 && now >= receivedAt && now - receivedAt <= STATE_FRESHNESS_MS
    && Number.isFinite(state.runtimeAgeSeconds) && state.runtimeAgeSeconds < 5
    && state.creditSum === 0 && ['idle', 'no_credit', 'stopped'].includes(state.phase)
    && !state.activeSessionId && !state.activeMode && !state.armedMode && !state.requestedOutput
    && !state.licenseLocked && !state.lastError && state.lastIoOk === true
    && !state.powerRecoveryAvailable && !paymentPending)
}
