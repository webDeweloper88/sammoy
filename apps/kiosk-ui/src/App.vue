<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { api, changePassword, getParameters, login, me, saveParameters } from './api'
import TouchKeyboard from './TouchKeyboard.vue'
import OwnerPages from './OwnerPages.vue'
import WalletSettings from './WalletSettings.vue'
import AdminPages from './AdminPages.vue'
const theme = ref(localStorage.getItem('sammoy-ui-theme') === 'dark' ? 'dark' : 'light')
function applyTheme() { document.documentElement.dataset.theme = theme.value; localStorage.setItem('sammoy-ui-theme', theme.value) }
function toggleTheme() { theme.value = theme.value === 'light' ? 'dark' : 'light'; applyTheme() }
applyTheme()
const page = ref('parameters')
const account = ref(null)
const pageDirty = ref(false)
const pendingPage = ref('')
const navLabels = { ru: ['Параметры', 'Отчёты', 'VIP и карты', 'Экран мойки', 'Telegram', 'Кошелёк', 'Учётная запись'], uz: ['Sozlamalar', 'Hisobotlar', 'VIP va kartalar', 'Yuvish ekrani', 'Telegram', 'Hamyon', 'Hisob'], en: ['Settings', 'Reports', 'VIP & cards', 'Wash screen', 'Telegram', 'Wallet', 'Account'] }
const pageKeys = ['parameters', 'reports', 'cards', 'kiosk-settings', 'telegram', 'wallet', 'account']
const adminKeys = ['diagnostics', 'connections', 'license', 'click', 'maintenance']
const visiblePages = computed(() => account.value?.role === 'admin' ? [...adminKeys, 'account'] : pageKeys)
const adminLabels = {ru:['Диагностика','Подключение','Лицензия','Click','Обслуживание'],uz:['Diagnostika','Ulanish','Litsenziya','Click','Xizmat'],en:['Diagnostics','Connection','License','Click','Maintenance']}
const pageLabel = key => adminKeys.includes(key) ? adminLabels[language.value][adminKeys.indexOf(key)] : navLabels[language.value][pageKeys.indexOf(key)]
const routeFor = key => '/' + (account.value?.role === 'admin' ? 'admin' : 'owner') + '/' + key
function enterPage() { const requested = location.pathname.split('/').pop(); page.value = visiblePages.value.includes(requested) ? requested : account.value?.role === 'admin' ? 'diagnostics' : 'parameters'; window.history.replaceState(null, '', routeFor(page.value)); if(page.value === 'parameters') return load() }
function navigate(value, force = false) {
  if (!force && (dirty.value || pageDirty.value)) { pendingPage.value = value; return }
  pageDirty.value = false; dirty.value = false; pendingPage.value = '';
  if(value === 'logout') { signOut(); return }
  page.value = value
  window.history.pushState(null, '', routeFor(value))
  if (value === 'parameters') load()
}
window.addEventListener('beforeunload', event => { if (dirty.value || pageDirty.value) { event.preventDefault(); event.returnValue = '' } })
window.addEventListener('popstate', () => { if (token.value) { const target = location.pathname.split('/').pop(); navigate(visiblePages.value.includes(target) ? target : visiblePages.value[0]) } })

const modes = ['water', 'foam', 'osmos', 'nano', 'wax', 'chem', 'vacuum', 'air']
const labels = {
  ru: {
    owner: 'Параметры мойки', intro: 'Тарифы и правила работы поста', login: 'Логин', password: 'Пароль', enter: 'Войти', logout: 'Выйти', changePassword: 'Смените пароль для первого входа', currentPassword: 'Текущий пароль', newPassword: 'Новый пароль (от 8 символов)', updatePassword: 'Сменить пароль',
    tariffs: 'Программы', amount: 'Сум', duration: 'Секунд', rate: 'Сум/мин', enabled: 'Включено',
    controls: 'Правила работы', freePause: 'Бесплатная пауза, сек', grace: 'Задержка после отпускания курка, сек',
    reset: 'Подтверждение отпущенного курка, сек', trigger: 'Требовать физический курок', recovery: 'Восстановление после отключения, сек',
    paid: 'Платная пауза', price: 'Стоимость, сум', pauseDuration: 'Длительность, сек',
    save: 'Сохранить', saving: 'Сохранение…', refresh: 'Обновить', saved: 'Параметры сохранены', loading: 'Загрузка…',
    noChange: 'Текущие значения загружены из контроллера. Сохранение применяет их сразу.',
    water: 'Вода', foam: 'Пена', osmos: 'Осмос', nano: 'Нано', wax: 'Воск', chem: 'Химия', vacuum: 'Пылесос', air: 'Воздух'
  },
  uz: {
    owner: 'Yuvish sozlamalari', intro: 'Tariflar va post qoidalari', login: 'Login', password: 'Parol', enter: 'Kirish', logout: 'Chiqish', changePassword: 'Birinchi kirishda parolni almashtiring', currentPassword: 'Joriy parol', newPassword: 'Yangi parol (kamida 8 belgi)', updatePassword: 'Parolni almashtirish',
    tariffs: 'Dasturlar', amount: 'So‘m', duration: 'Soniya', rate: 'So‘m/daq', enabled: 'Yoqilgan',
    controls: 'Ishlash qoidalari', freePause: 'Bepul pauza, soniya', grace: 'Tugmani qo‘yib yuborish kechikishi, soniya',
    reset: 'Tugma qo‘yib yuborilganini tasdiqlash, soniya', trigger: 'Jismoniy tugma talab qilinsin', recovery: 'Elektr uzilgandan keyin tiklash, soniya',
    paid: 'Pullik pauza', price: 'Narx, so‘m', pauseDuration: 'Davomiyligi, soniya',
    save: 'Saqlash', saving: 'Saqlanmoqda…', refresh: 'Yangilash', saved: 'Sozlamalar saqlandi', loading: 'Yuklanmoqda…',
    noChange: 'Joriy qiymatlar kontrollerdan yuklandi. Saqlash ularni darhol qo‘llaydi.',
    water: 'Suv', foam: 'Ko‘pik', osmos: 'Osmos', nano: 'Nano', wax: 'Mum', chem: 'Kimyo', vacuum: 'Changyutgich', air: 'Havo'
  },
  en: {
    owner: 'Wash settings', intro: 'Rates and station rules', login: 'Login', password: 'Password', enter: 'Sign in', logout: 'Sign out', changePassword: 'Change your password on first sign-in', currentPassword: 'Current password', newPassword: 'New password (8 characters minimum)', updatePassword: 'Change password',
    tariffs: 'Programs', amount: 'Sum', duration: 'Seconds', rate: 'Sum/min', enabled: 'Enabled',
    controls: 'Operating rules', freePause: 'Free pause, seconds', grace: 'Trigger release grace, seconds',
    reset: 'Trigger release confirmation, seconds', trigger: 'Require physical trigger', recovery: 'Power recovery window, seconds',
    paid: 'Paid pause', price: 'Price, sum', pauseDuration: 'Duration, seconds',
    save: 'Save', saving: 'Saving…', refresh: 'Refresh', saved: 'Settings saved', loading: 'Loading…',
    noChange: 'Current values were loaded from the controller. Saving applies them immediately.',
    water: 'Water', foam: 'Foam', osmos: 'Osmos', nano: 'Nano', wax: 'Wax', chem: 'Chemistry', vacuum: 'Vacuum', air: 'Air'
  }
}
const touchLabels = {
  ru: { access: 'Вход в управление', accessHint: 'Для владельца и администратора мойки. Выберите поле и введите данные на экранной клавиатуре.', account: 'Учётная запись', console: 'Управление постом', unsaved: 'Есть несохранённые изменения', show: 'Показать пароль', confirm: 'Повторите новый пароль', mismatch: 'Новые пароли не совпадают' },
  uz: { access: 'Boshqaruvga kirish', accessHint: 'Yuvish egasi va administratori uchun. Maydonni tanlang va ekran klaviaturasida ma’lumotlarni kiriting.', account: 'Hisob', console: 'Post boshqaruvi', unsaved: 'Saqlanmagan o‘zgarishlar bor', show: 'Parolni ko‘rsatish', confirm: 'Yangi parolni takrorlang', mismatch: 'Yangi parollar mos emas' },
  en: { access: 'Management sign-in', accessHint: 'For the wash owner and administrator. Select a field and enter your details using the on-screen keyboard.', account: 'Your account', console: 'Station management', unsaved: 'Unsaved changes', show: 'Show password', confirm: 'Confirm new password', mismatch: 'New passwords do not match' }
}
const storedLanguage = localStorage.getItem('sammoy-ui-language')
const language = ref(labels[storedLanguage] ? storedLanguage : 'ru')
const t = key => labels[language.value][key] ?? touchLabels[language.value][key]
const token = ref(sessionStorage.getItem('sammoy-owner-token') || '')
const credentials = reactive({ login: '', password: '' })
const passwordChangeRequired = ref(false)
const passwordChange = reactive({ current: '', next: '', confirm: '' })
const showPasswords = ref(false)
const loginInput = ref(null)
const parameters = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const dirty = ref(false)

function updateAccount(value) { account.value=value.user; token.value=value.access_token; sessionStorage.setItem('sammoy-owner-token',token.value) }

function openInstall() { window.location.assign('/install') }

function setLanguage(value) {
  language.value = value
  localStorage.setItem('sammoy-ui-language', value)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await getParameters(token.value)
    parameters.value = structuredClone(result.parameters)
    window.history.replaceState(null, '', routeFor(page.value))
    dirty.value = false
  } catch (exc) {
    if (/HTTP 401|HTTP 403/.test(exc.message)) signOut()
    error.value = exc.message
  } finally {
    loading.value = false
  }
}

async function signIn() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await login(credentials.login.trim(), credentials.password)
    if (!['owner', 'admin'].includes(result.user?.role)) throw new Error('Owner/Admin access required')
    account.value = result.user
    token.value = result.access_token
    sessionStorage.setItem('sammoy-owner-token', token.value)
    passwordChangeRequired.value = Boolean(result.user?.must_change_password)
    if (passwordChangeRequired.value) passwordChange.current = credentials.password
    credentials.password = ''
    if (!passwordChangeRequired.value) await enterPage()
  } catch (exc) {
    error.value = exc.message
  } finally {
    loading.value = false
  }
}

async function updatePassword() {
  if (loading.value) return
  if (passwordChange.next !== passwordChange.confirm) { error.value = t('mismatch'); return }
  loading.value = true
  error.value = ''
  try {
    const result = await changePassword(token.value, passwordChange.current, passwordChange.next)
    account.value = result.user
    token.value = result.access_token
    sessionStorage.setItem('sammoy-owner-token', token.value)
    passwordChange.current = ''
    passwordChange.next = ''
    passwordChange.confirm = ''
    showPasswords.value = false
    passwordChangeRequired.value = false
    await enterPage()
  } catch (exc) {
    error.value = exc.message
  } finally {
    loading.value = false
  }
}

async function signOut() {
  const oldToken = token.value
  dirty.value=false; pageDirty.value=false; account.value=null
  token.value = ''
  page.value = 'parameters'
  parameters.value = null
  passwordChangeRequired.value = false
  passwordChange.current = ''
  passwordChange.next = ''
  passwordChange.confirm = ''
  showPasswords.value = false
  credentials.password = ''
  sessionStorage.removeItem('sammoy-owner-token')
  window.history.replaceState(null, '', '/login')
  nextTick(() => loginInput.value?.focus())
  if(oldToken) { try { await api('/api/auth/logout',{token:oldToken,method:'POST'}) } catch {} }
}

window.addEventListener('sammoy-session-expired', () => { signOut(); error.value = language.value === 'ru' ? 'Сеанс истёк. Войдите снова.' : 'Session expired. Sign in again.' })

function validNumber(value, min = 0) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min
}

function markDirty() { dirty.value = true; notice.value = '' }

const valid = computed(() => {
  const p = parameters.value
  if (!p) return false
  if(p.topUpBonus && (!Number.isInteger(p.topUpBonus.percent)||p.topUpBonus.percent<0||p.topUpBonus.percent>100))return false
  if (![p.freePauseSeconds, p.triggerGraceSeconds, p.triggerResetConfirmSeconds, p.powerRecoverySeconds].every(v => validNumber(v))) return false
  if (!validNumber(p.paidPause?.amountSum) || !validNumber(p.paidPause?.durationSeconds, 1)) return false
  return modes.every(mode => validNumber(p.tariffs?.[mode]?.amountSum) && validNumber(p.tariffs?.[mode]?.durationSeconds, 1))
})

async function save() {
  if (!valid.value || !dirty.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await saveParameters(token.value, parameters.value)
    parameters.value = structuredClone(result.parameters)
    dirty.value = false
    notice.value = t('saved')
  } catch (exc) {
    error.value = exc.message
  } finally {
    saving.value = false
  }
}

function rate(tariff) {
  const amount = Number(tariff?.amountSum || 0)
  const duration = Number(tariff?.durationSeconds || 0)
  return duration > 0 ? Math.round(amount * 60 / duration).toLocaleString() : '—'
}

onMounted(async () => {
  if (!token.value) {
    window.history.replaceState(null, '', '/login')
    await nextTick()
    loginInput.value?.focus()
    return
  }
  try {
    const user = await me(token.value)
    account.value = user
    passwordChangeRequired.value = Boolean(user.must_change_password)
    if (!passwordChangeRequired.value) await enterPage()
  } catch (exc) {
    signOut()
    error.value = exc.message
  }
})
</script>

<template>
  <main class="shell" :class="{ 'access-shell': !token || passwordChangeRequired }">
    <header class="topbar">
      <div class="brand"><strong>Labrixwash</strong><span>{{ t('console') }}</span></div>
      <div class="top-actions"><button class="quiet" @click="toggleTheme" :aria-label="language === 'ru' ? 'Сменить тему' : 'Change theme'">{{ theme === 'light' ? '◐ Dark' : '☀ Light' }}</button>
        <div class="language" aria-label="Language"><button v-for="item in ['ru', 'uz', 'en']" :key="item" :class="{ active: language === item }" @click="setLanguage(item)">{{ item.toUpperCase() }}</button></div>
        <button v-if="token" class="quiet" @click="navigate('logout')">{{ t('logout') }}</button>
      </div>
    </header>

    <nav v-if="token && !passwordChangeRequired" class="owner-nav" :aria-label="account?.role === 'admin' ? 'Admin' : 'Owner'"><button v-for="item in visiblePages" :key="item" v-show="item !== 'reports' || account?.role === 'owner'" class="quiet" :class="{selected:page === item}" @click="navigate(item)">{{ pageLabel(item) }}</button></nav>
    <section class="heading" v-if="!token || passwordChangeRequired || page === 'parameters'"><h1>{{ t(token ? 'owner' : 'access') }}</h1><p>{{ t(token ? 'intro' : 'accessHint') }}</p></section>

    <div v-if="error" class="message error" role="alert">{{ error }}</div>
    <div v-if="notice" class="message success" role="status">{{ notice }}</div>

    <div class="workspace" :class="{ 'access-workspace': !token || passwordChangeRequired }">
    <form v-if="!token" class="login card" @submit.prevent="signIn">
      <h2>{{ t('account') }}</h2>
      <label>{{ t('login') }}<input ref="loginInput" v-model="credentials.login" autocomplete="username" maxlength="80" required /></label>
      <label>{{ t('password') }}<input v-model="credentials.password" :type="showPasswords ? 'text' : 'password'" autocomplete="current-password" maxlength="200" required /></label>
      <label class="show-password"><input v-model="showPasswords" type="checkbox" />{{ t('show') }}</label>
      <button class="primary" :disabled="loading">{{ loading ? t('loading') : t('enter') }}</button><button type="button" class="quiet" @click="openInstall">{{ language === 'ru' ? 'Установка поста' : language === 'uz' ? 'Postni sozlash' : 'Station setup' }}</button>
    </form>

    <form v-else-if="passwordChangeRequired" class="login card" @submit.prevent="updatePassword">
      <h2>{{ t('changePassword') }}</h2>
      <label>{{ t('currentPassword') }}<input v-model="passwordChange.current" :type="showPasswords ? 'text' : 'password'" autocomplete="current-password" maxlength="200" required /></label>
      <label>{{ t('newPassword') }}<input v-model="passwordChange.next" :type="showPasswords ? 'text' : 'password'" minlength="8" maxlength="200" autocomplete="new-password" required /></label>
      <label>{{ t('confirm') }}<input v-model="passwordChange.confirm" :type="showPasswords ? 'text' : 'password'" minlength="8" maxlength="200" autocomplete="new-password" required /></label>
      <label class="show-password"><input v-model="showPasswords" type="checkbox" />{{ t('show') }}</label>
      <button class="primary" :disabled="loading">{{ t('updatePassword') }}</button>
    </form>

    <div v-else-if="loading && !parameters" class="card loading">{{ t('loading') }}</div>
    <AdminPages v-else-if="account?.role === 'admin' && adminKeys.includes(page)" :key="page" :page="page" :token="token" :language="language" @dirty="pageDirty = $event" />
    <WalletSettings v-else-if="account?.role==='owner' && page==='wallet'" :token="token" @dirty="pageDirty=$event" :language="language"/>
      <OwnerPages v-else-if="page !== 'parameters'" :key="page" :page="page" :token="token" :language="language" :account="account" @dirty="pageDirty = $event" @account="updateAccount" />
    <template v-else-if="parameters">
      <div class="toolbar"><p :class="{ 'unsaved': dirty }">{{ t(dirty ? 'unsaved' : 'noChange') }}</p><div><button class="quiet" :disabled="loading || saving" @click="navigate('parameters')">{{ t('refresh') }}</button><button class="primary" :disabled="!valid || !dirty || saving" @click="save">{{ saving ? t('saving') : t('save') }}</button></div></div>
      <form @submit.prevent="save" @input="markDirty" @change="markDirty">
        <section class="card"><div class="card-head"><h2>{{ language==='ru'?'Бонус за пополнение':language==='uz'?'Balans to‘ldirish bonusi':'Top-up bonus' }}</h2></div><div class="content fields" v-if="parameters.topUpBonus"><label class="show-password"><input v-model="parameters.topUpBonus.enabled" type="checkbox"/>{{ language==='ru'?'Начислять бонус':language==='uz'?'Bonus hisoblash':'Award bonus' }}</label><label>{{ language==='ru'?'Бонус, %':language==='uz'?'Bonus, %':'Bonus, %' }}<input v-model.number="parameters.topUpBonus.percent" type="number" min="0" max="100" step="1" required/></label><p>{{ language==='ru'?'Только новые пополнения наличными и Click на этом посту. Перенос на карту не начисляет бонус повторно. Сначала расходуется бонус.':language==='uz'?'Faqat ushbu postdagi yangi naqd va Click to‘lovlari uchun. Kartaga ko‘chirishda bonus qayta hisoblanmaydi. Avval bonus sarflanadi.':'Only new cash and Click top-ups at this station. Card transfers never award another bonus. Bonus is spent first.' }}</p><p v-if="parameters.topUpBonus.enabled">50 000 + {{ (50000*parameters.topUpBonus.percent/100).toLocaleString('ru-RU') }} = <strong>{{ (50000+50000*parameters.topUpBonus.percent/100).toLocaleString('ru-RU') }} so‘m</strong></p></div></section>
        <section class="card"><div class="card-head"><h2>{{ t('tariffs') }}</h2></div>
          <div class="table-wrap"><table><thead><tr><th>{{ t('tariffs') }}</th><th>{{ t('amount') }}</th><th>{{ t('duration') }}</th><th>{{ t('rate') }}</th><th>{{ t('enabled') }}</th></tr></thead><tbody>
            <tr v-for="mode in modes" :key="mode"><th>{{ t(mode) }}</th><td><input v-model.number="parameters.tariffs[mode].amountSum" :aria-label="`${t(mode)} — ${t('amount')}`" type="number" min="0" step="1" /></td><td><input v-model.number="parameters.tariffs[mode].durationSeconds" :aria-label="`${t(mode)} — ${t('duration')}`" type="number" min="1" step="1" /></td><td class="rate">{{ rate(parameters.tariffs[mode]) }}</td><td><label class="table-toggle"><input v-model="parameters.tariffs[mode].enabled" type="checkbox" :aria-label="`${t(mode)} — ${t('enabled')}`" /></label></td></tr>
          </tbody></table></div>
        </section>
        <div class="grid"><section class="card"><div class="card-head"><h2>{{ t('controls') }}</h2></div><div class="fields">
          <label>{{ t('freePause') }}<input v-model.number="parameters.freePauseSeconds" type="number" min="0" step="1" /></label>
          <label>{{ t('grace') }}<input v-model.number="parameters.triggerGraceSeconds" type="number" min="0" step="0.1" /></label>
          <label>{{ t('reset') }}<input v-model.number="parameters.triggerResetConfirmSeconds" type="number" min="0" step="0.1" /></label>
          <label>{{ t('recovery') }}<input v-model.number="parameters.powerRecoverySeconds" type="number" min="0" step="1" /></label>
          <label class="switch">{{ t('trigger') }}<input v-model="parameters.requireTotalStopTrigger" type="checkbox" /></label>
        </div></section>
        <section class="card"><div class="card-head"><h2>{{ t('paid') }}</h2></div><div class="fields">
          <label class="switch">{{ t('enabled') }}<input v-model="parameters.paidPause.enabled" type="checkbox" /></label>
          <label>{{ t('price') }}<input v-model.number="parameters.paidPause.amountSum" type="number" min="0" step="1" /></label>
          <label>{{ t('pauseDuration') }}<input v-model.number="parameters.paidPause.durationSeconds" type="number" min="1" step="1" /></label>
        </div></section></div>
        <div class="bottom-save"><button class="primary" type="submit" :disabled="!valid || !dirty || saving">{{ saving ? t('saving') : t('save') }}</button></div>
      </form>
    </template>
    <div v-if="pendingPage" class="confirm-backdrop"><section class="card confirm-dialog" role="alertdialog" aria-modal="true"><h2>{{ language === 'ru' ? 'Не сохранять изменения?' : language === 'uz' ? 'O‘zgarishlar saqlanmasinmi?' : 'Discard changes?' }}</h2><div class="actions"><button class="quiet" @click="pendingPage = ''">{{ language === 'ru' ? 'Остаться' : 'Cancel' }}</button><button class="primary" @click="navigate(pendingPage, true)">{{ language === 'ru' ? 'Не сохранять' : 'Discard' }}</button></div></section></div>
    <TouchKeyboard :language="language" :class="{ 'auth-keyboard': !token || passwordChangeRequired }" />
    </div>
  </main>
</template>
