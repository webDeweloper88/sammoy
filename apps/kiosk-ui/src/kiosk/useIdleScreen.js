import { ref, onMounted, onUnmounted, watch } from 'vue'
import { canAttract, IDLE_TIMEOUT_MS } from './idle-policy.js'

// Supply the existing wash-state feed; this composable never controls equipment.
export function useIdleScreen(state, receivedAt, paymentPending) {
  const visible = ref(false)
  let lastActivity = Date.now()
  let timer
  const activity = () => { lastActivity = Date.now() }
  const wake = () => { visible.value = false; activity() }
  const eligible = () => canAttract(state.value, { receivedAt: receivedAt.value, paymentPending: paymentPending?.value })
  const check = () => {
    if (!eligible()) wake()
    else if (Date.now() - lastActivity >= IDLE_TIMEOUT_MS) visible.value = true
  }
  watch([state, receivedAt, () => paymentPending?.value], check, { deep: true })
  onMounted(() => {
    activity()
    window.addEventListener('pointerdown', activity, true)
    window.addEventListener('keydown', activity, true)
    timer = window.setInterval(check, 250)
  })
  onUnmounted(() => {
    clearInterval(timer)
    window.removeEventListener('pointerdown', activity, true)
    window.removeEventListener('keydown', activity, true)
  })
  return { visible, wake, activity }
}
