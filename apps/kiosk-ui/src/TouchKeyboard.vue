<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch, useAttrs } from 'vue'

defineOptions({ inheritAttrs: false })
const attrs = useAttrs()
const props = defineProps({ language: { type: String, default: 'ru' } })
const input = shallowRef(null)
const modal = ref(false), keyboard = ref(null)
let sizeObserver
watch(keyboard, element => {
  sizeObserver?.disconnect()
  if (!element) return
  sizeObserver = new ResizeObserver(() => {
    document.body.style.setProperty('--touch-keyboard-height', element.getBoundingClientRect().height + 'px')
  })
  sizeObserver.observe(element)
})
const upper = ref(false)
const symbols = ref(false)
const alphabet = ref('en')
const inputType = ref('')
const integer = computed(() => input.value?.dataset.keyboard === 'integer')
const numeric = computed(() => inputType.value === 'number' || integer.value)
const words = {
  ru: { title: 'Экранная клавиатура', close: 'Готово', erase: 'Стереть', clear: 'Очистить', space: 'Пробел', next: 'Далее' },
  uz: { title: 'Ekran klaviaturasi', close: 'Tayyor', erase: 'O‘chirish', clear: 'Tozalash', space: 'Bo‘sh joy', next: 'Keyingi' },
  en: { title: 'On-screen keyboard', close: 'Done', erase: 'Backspace', clear: 'Clear', space: 'Space', next: 'Next' }
}
const t = key => (words[props.language] || words.ru)[key]
const rows = computed(() => {
  if (numeric.value) return [['1', '2', '3'], ['4', '5', '6'], ['7', '8', '9'], integer.value?['0']:['.', '0']]
  if (symbols.value) return ['1234567890', '!@#$%^&*()', '-_=+[]{}\\|', ';:\'",.<>/?`~'].map(row => [...row])
  const letters = alphabet.value === 'ru'
    ? ['1234567890', 'йцукенгшщзхъ', 'фывапролджэ', 'ячсмитьбюё']
    : ['1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm']
  return letters.map(row => [...(upper.value ? row.toUpperCase() : row)])
})
const fieldLabel = computed(() => input.value?.getAttribute('aria-label') || input.value?.closest('label')?.childNodes[0]?.textContent?.trim() || '')
let previousInputMode = null

function restoreInputMode() {
  if (!input.value) return
  if (inputType.value === 'number') {
    input.value.type = 'number'
    input.value.dispatchEvent(new Event('input', { bubbles: true }))
  }
  if (previousInputMode === null) input.value.removeAttribute('inputmode')
  else input.value.setAttribute('inputmode', previousInputMode)
}

function focusInput(event) {
  const target = event.target
  if (!(target instanceof HTMLInputElement) || !['text', 'password', 'number', 'email', 'search', 'tel', 'url'].includes(target.type) || target.disabled || target.readOnly) return
  if (input.value !== target) {
    restoreInputMode()
    input.value = target
    inputType.value = target.type
    if (numeric.value) target.type = 'text'
    previousInputMode = target.getAttribute('inputmode')
    target.setAttribute('inputmode', 'none')
  }
  modal.value = Boolean(target.closest('[role=dialog], [role=alertdialog]'))
  document.body.classList.toggle('modal-keyboard-open', modal.value)
  document.body.classList.add('keyboard-open')
  nextTick(() => target.scrollIntoView({ block: 'center', behavior: 'auto' }))
}

function close() {
  restoreInputMode()
  input.value?.blur()
  input.value = null
  modal.value = false
  document.body.classList.remove('keyboard-open', 'modal-keyboard-open')
  document.body.style.removeProperty('--touch-keyboard-height')
}

function edit(key) {
  const target = input.value
  if (!target?.isConnected || target.disabled) { close(); return }
  const value = target.value
  const start = target.selectionStart ?? value.length
  const end = target.selectionEnd ?? value.length
  let next, position
  if (key === 'clear') {
    next = ''; position = 0
  } else if (key === 'backspace') {
    const from = start === end ? Math.max(0, start - (target.dataset.format==='activation-code' && value[start-1]==='-'?2:1)) : start
    next = value.slice(0, from) + value.slice(end); position = from
  } else {
    next = value.slice(0, start) + key + value.slice(end); position = start + key.length
  }
  if (target.maxLength >= 0 && next.length > target.maxLength) return
  // Number inputs cannot retain a trailing decimal point. Use a text input
  // while the keypad is open so Vue's .number modifier receives each edit.
  target.value = next
  target.dispatchEvent(new Event('input', { bubbles: true }))
  target.focus({ preventScroll: true })
  if (target.type !== 'number' && target.value === next) target.setSelectionRange(position, position)
}

function nextField() {
  const target = input.value
  if (!target) return
  const form = target.closest('[role=dialog], [role=alertdialog]') || target.closest('form')
  const fields = [...(form || document).querySelectorAll('input:not([type=checkbox]):not([disabled])')]
  const next = fields[fields.indexOf(target) + 1]
  if (next) next.focus()
  else close()
}

function keydown(event) { if (event.key === 'Escape') close() }
function watchRemoval() { if (input.value && !input.value.isConnected) close() }
let observer
onMounted(() => {
  document.addEventListener('focusin', focusInput)
  document.addEventListener('keydown', keydown)
  observer = new MutationObserver(watchRemoval)
  observer.observe(document.body, { childList: true, subtree: true })
})
onUnmounted(() => {
  close()
  document.removeEventListener('focusin', focusInput)
  document.removeEventListener('keydown', keydown)
  observer?.disconnect()
  sizeObserver?.disconnect()
})
</script>

<template>
  <Teleport to="body" :disabled="!modal">
  <section v-if="input" ref="keyboard" class="touch-keyboard" :class="[attrs.class, { numeric, 'dialog-keyboard': modal }]" :aria-label="t('title')" @pointerdown.prevent>
    <header><div><strong>{{ t('title') }}</strong><small>{{ fieldLabel }}</small></div><button type="button" class="keyboard-done" @click="close">{{ t('close') }} ✓</button></header>
    <div class="keyboard-keys">
      <div v-for="(row, index) in rows" :key="index" class="keyboard-row">
        <button v-for="key in row" :key="key" type="button" @click="edit(key)">{{ key }}</button>
      </div>
    </div>
    <div class="keyboard-actions">
      <button v-if="!numeric" type="button" :aria-pressed="upper" @click="upper = !upper">⇧ Shift</button>
      <button v-if="!numeric" type="button" @click="symbols = !symbols">{{ symbols ? 'ABC' : '#+=' }}</button>
      <button v-if="!numeric" type="button" @click="alphabet = alphabet === 'en' ? 'ru' : 'en'; symbols = false">{{ alphabet === 'en' ? 'РУС' : 'ENG' }}</button>
      <button v-if="!numeric" type="button" class="keyboard-space" @click="edit(' ')">{{ t('space') }}</button>
      <button type="button" @click="edit('backspace')">⌫ {{ t('erase') }}</button>
      <button type="button" @click="edit('clear')">{{ t('clear') }}</button>
      <button type="button" @click="nextField">{{ t('next') }} →</button>
    </div>
  </section>
  </Teleport>
</template>
