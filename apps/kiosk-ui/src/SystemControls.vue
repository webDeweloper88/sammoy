<script setup>
import { computed, ref, onUnmounted } from 'vue'
import {maintenanceActive} from './maintenance-state.js'
import { api, login } from './api'
const props = defineProps({ language: { default: 'ru' }, resets: Boolean, initialLogin: { default: '' } })
const text = {
  ru: { reboot:'Перезапустить', poweroff:'Выключить', settings:'Сбросить настройки', full:'Полный сброс', title:'Управление устройством', login:'Логин Owner/Admin', password:'Пароль', cancel:'Отмена', confirm:'Подтвердить', phrase:'Введите', isolated:'Другие посты этой мойки выключены или отключены от локальной сети. Старый резервный не будет возвращён без повторной установки.', warning:'Пост должен быть свободен, без денег и VIP-сеанса. Команда относится только к этому устройству.', settingsHint:'Вернутся стандартные тарифы, правила паузы и оформление. Деньги, карты/VIP, история, активация, аккаунты, сеть, подключение оборудования и фильтр купюроприёмника сохранятся.', fullHint:'Будут удалены деньги общего кошелька на этом узле, карты/VIP, история, Telegram и привязка к мойке. Логины и пароли, сеть, идентичность устройства и счётчик/фильтр купюроприёмника сохранятся. Устройство вернётся в /install. Для сброса нужен Admin.', powerHint:'Оборудование будет остановлено, данные сохранены. Для выключения дождитесь остановки экрана перед отключением питания.', accepted:'Команда принята. Дождитесь завершения операции. При ошибке обратитесь к установщику; повторно сброс не запускайте.', install:'Открыть установку', reload:'Обновить страницу', working:'Подтверждение…' },
  uz: { reboot:'Qayta ishga tushirish', poweroff:'O‘chirish', settings:'Sozlamalarni tiklash', full:'To‘liq tiklash', title:'Qurilmani boshqarish', login:'Owner/Admin logini', password:'Parol', cancel:'Bekor qilish', confirm:'Tasdiqlash', phrase:'Kiriting', isolated:'Ushbu yuvishning boshqa postlari o‘chirilgan yoki mahalliy tarmoqdan uzilgan. Eski zaxira qayta o‘rnatilmasdan ulanmaydi.', warning:'Post bo‘sh, balans nol va VIP seansi yopilgan bo‘lishi kerak. Buyruq faqat shu qurilmaga tegishli.', settingsHint:'Tariflar, pauza qoidalari va ko‘rinish tiklanadi. Pul, kartalar/VIP, tarix, faollashtirish, hisoblar, tarmoq, uskuna ulanishi va banknota filtri saqlanadi.', fullHint:'Ushbu qurilmadagi umumiy hamyon puli, kartalar/VIP, tarix, Telegram va yuvishga bog‘lanish o‘chiriladi. Login/parollar, tarmoq, qurilma identifikatori va banknota hisoblagichi/filtri saqlanadi. /install qayta ochiladi. Admin kerak.', powerHint:'Uskuna to‘xtatiladi, ma’lumotlar saqlanadi. Quvvatni uzishdan oldin ekran o‘chishini kuting.', accepted:'Buyruq qabul qilindi. Amal tugashini kuting. Xatolik bo‘lsa o‘rnatuvchiga murojaat qiling; tiklashni qayta boshlamang.', install:'O‘rnatishni ochish', reload:'Sahifani yangilash', working:'Tasdiqlanmoqda…' },
  en: { reboot:'Restart', poweroff:'Shut down', settings:'Reset settings', full:'Full reset', title:'Device controls', login:'Owner/Admin login', password:'Password', cancel:'Cancel', confirm:'Confirm', phrase:'Type', isolated:'Other stations at this site are powered off or disconnected from the LAN. The old standby will not reconnect before reinstallation.', warning:'The station must be idle, with no credit or VIP session. This affects this device only.', settingsHint:'Restores default tariffs, pause rules and appearance. Money, cards/VIP, history, activation, accounts, network, hardware wiring and bill filter are preserved.', fullHint:'Deletes this node’s shared wallet money, cards/VIP, history, Telegram and site binding. Preserves logins/passwords, network, hardware identity and bill counter/filter. Returns to /install. Admin is required.', powerHint:'Stops equipment and saves data. Wait for the display to stop before disconnecting power.', accepted:'Command accepted. Wait for completion. If it fails, contact your installer; do not repeat the reset.', install:'Open setup', reload:'Reload page', working:'Confirming…' }
}
const t = computed(() => text[props.language] || text.ru)
const job=ref(null),jobState=ref('waiting'),checking=ref(false)
let pollTimer,redirectTimer
const progress=computed(()=>({ru:{waiting:'Ожидаем завершения операции. Во время перезапуска связь может временно пропадать.',completed:'Операция завершена. Открываем следующую страницу…',failed:'Операция остановлена с ошибкой. Обратитесь к установщику. Не запускайте сброс повторно.'},uz:{waiting:'Amal tugashi kutilmoqda. Qayta ishga tushishda aloqa vaqtincha uzilishi mumkin.',completed:'Amal tugadi. Keyingi sahifa ochilmoqda…',failed:'Amal xatolik bilan to‘xtadi. O‘rnatuvchiga murojaat qiling. Tiklashni qayta boshlamang.'},en:{waiting:'Waiting for completion. The connection may be temporarily unavailable during restart.',completed:'Operation complete. Opening the next page…',failed:'Operation stopped with an error. Contact your installer. Do not repeat the reset.'}}[props.language]||{waiting:'Waiting…'})[jobState.value])
const action = ref(''), name = ref(''), password = ref(''), phrase = ref(''), isolated = ref(false), busy = ref(false), accepted = ref(false), error = ref('')
function open(value) { action.value=value; name.value=props.initialLogin; password.value=''; phrase.value=''; isolated.value=false; accepted.value=false; error.value='' }
async function submit() {
  if(busy.value||accepted.value)return
  busy.value=true; error.value=''
  try {
    // Reuse the normal rate-limited login; never retain the password or token.
    const auth=await login(name.value.trim(),password.value)
    password.value=''
    job.value=await api('/api/system/actions',{token:auth.access_token,method:'POST',body:JSON.stringify({action:action.value,request_id:crypto.randomUUID ? crypto.randomUUID() : uuid(),confirmation:phrase.value,cluster_isolated:isolated.value})})
    accepted.value=true;maintenanceActive.value=true;jobState.value='waiting'
    if(action.value!=='poweroff')pollTimer=setInterval(checkStatus,1500)
  } catch(e) { error.value=e.message } finally { busy.value=false }
}
async function checkStatus(){
  if(checking.value||!job.value?.request_id)return
  checking.value=true
  try{
    const result=await api('/api/system/actions/'+job.value.request_id,{signal:AbortSignal.timeout(4000)})
    if(result.status==='failed'){jobState.value='failed';clearInterval(pollTimer)}
    if(result.status==='completed'){
      jobState.value='completed';clearInterval(pollTimer)
      redirectTimer=setTimeout(()=>window.location.assign(action.value==='full'?'/install':'/login'),1500)
    }
  }catch(e){if(e.status===404){jobState.value='failed';clearInterval(pollTimer)} /* Never repeat the action. */ }
  finally{checking.value=false}
}
onUnmounted(()=>{clearInterval(pollTimer);clearTimeout(redirectTimer)})
// LAN HTTP does not expose crypto.randomUUID on every kiosk browser.
function uuid() { const a=crypto.getRandomValues(new Uint8Array(16));a[6]=(a[6]&15)|64;a[8]=(a[8]&63)|128;return [...a].map((v,i)=>([4,6,8,10].includes(i)?'-':'')+v.toString(16).padStart(2,'0')).join('') }
</script>
<template>
  <section class="system-controls">
    <div class="actions"><button type="button" class="quiet" @click="open('reboot')">⟳ {{ t.reboot }}</button><button type="button" class="quiet" @click="open('poweroff')">⏻ {{ t.poweroff }}</button></div>
    <template v-if="resets"><h3>{{ t.title }}</h3><div class="actions"><button type="button" class="quiet" @click="open('settings')">{{ t.settings }}</button><button type="button" class="quiet reset-danger" @click="open('full')">{{ t.full }}</button></div></template>
    <Teleport to="body"><div v-if="action" class="confirm-backdrop"><form class="card system-dialog" role="dialog" aria-modal="true" :aria-label="t[action]" @submit.prevent="submit">
      <h2>{{ t[action] }}</h2>
      <template v-if="!accepted"><p>{{ t.warning }}</p><p>{{ action==='full'?t.fullHint:action==='settings'?t.settingsHint:t.powerHint }}</p>
        <label v-if="action==='full'" class="isolation-check"><input v-model="isolated" type="checkbox" required />{{ t.isolated }}</label>
        <label>{{ t.login }}<input v-model="name" autocomplete="username" maxlength="80" required /></label>
        <label>{{ t.password }}<input v-model="password" type="password" autocomplete="current-password" maxlength="200" required /></label>
        <label>{{ t.phrase }} <strong>{{ action.toUpperCase() }}</strong><input v-model="phrase" autocomplete="off" :placeholder="action.toUpperCase()" required /></label>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <div class="actions"><button type="button" class="quiet" :disabled="busy" @click="action=''">{{ t.cancel }}</button><button class="primary" :disabled="busy||phrase!==action.toUpperCase()||(action==='full'&&!isolated)">{{ busy?t.working:t.confirm }}</button></div>
      </template>
      <template v-else><p role="status">{{ action==='poweroff'?t.accepted:progress }}</p><a v-if="jobState==='completed'&&action==='full'" href="/install">{{ t.install }}</a><a v-else-if="jobState==='failed'" href="/login">{{ t.reload }}</a></template>
    </form></div></Teleport>
  </section>
</template>
<style scoped>
.system-controls{margin-top:24px}.system-controls>.actions{display:flex;flex-wrap:wrap;gap:12px}.system-controls>.actions>button{flex:1;min-height:52px}.reset-danger{color:var(--danger,#e5475e);border-color:currentColor}.system-dialog{box-sizing:border-box;width:min(600px,calc(100vw - 32px));max-height:90dvh;overflow:auto;padding:28px;display:grid;gap:18px}.system-dialog p{margin:0;line-height:1.55}.system-dialog label{display:grid;gap:8px}.system-dialog .isolation-check{display:flex;align-items:flex-start;gap:12px}.isolation-check input{width:24px;height:24px;flex-shrink:0}.system-dialog .actions{display:flex;gap:12px;flex-wrap:wrap}.system-dialog .actions>*{flex:1}.system-dialog h2{margin:0}
</style>
