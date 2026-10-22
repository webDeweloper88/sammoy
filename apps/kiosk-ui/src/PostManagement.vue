<script setup>
import {ref,computed,onMounted,onUnmounted} from 'vue'
import {api,login} from './api'
import PeerAddress from './PeerAddress.vue'
import StationLink from './StationLink.vue'
import {networkContext} from './install-inputs.js'
const props=defineProps({token:String,language:{default:'ru'},disabled:Boolean,availability:Object})
const emit=defineEmits(['changed','busy'])
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
const data=ref(null),kind=ref(''),target=ref(3),address=ref(''),fenced=ref(false),single=ref(false)
const preview=ref(null),error=ref(''),busy=ref(false),confirm=ref(false),password=ref(''),notice=ref('')
const cfg=computed(()=>data.value?.configuration||{})
const job=computed(()=>data.value?.operation)
const pending=computed(()=>job.value&&!['completed','retired','aborted','superseded'].includes(job.value.stage))
const primary=computed(()=>cfg.value.local_post===cfg.value.primary_post)
const standby=computed(()=>cfg.value.local_post===cfg.value.standby_post)
const origin=computed(()=>job.value?.before?.primary_post===cfg.value.local_post)
function liveClass(post){return props.availability?.nodes?.find(n=>n.post===post)?.state||'unknown'}
function live(post){const node=props.availability?.nodes?.find(n=>n.post===post);return node?.state==='available'?tr('Сейчас доступен','Hozir mavjud','Currently available'):node?.state==='unavailable'?tr('Сейчас недоступен','Hozir mavjud emas','Currently unavailable'):node?.state==='mismatch'?tr('Роли требуют проверки','Rollarni tekshirish kerak','Roles need verification'):tr('Нет свежей проверки связи','Yangi aloqa tekshiruvi yo‘q','No fresh connection check')}
const network=computed(()=>{let hostname=location.hostname;try{hostname=new URL(cfg.value.peer_urls?.[String(cfg.value.local_post)]||location.origin).hostname}catch{}return networkContext(null,hostname)})
let timer,stopped=false,observed=null,polling=false
const request=(url,options={})=>api('/api/wallet-management'+url,{token:props.token,...options})
const post=(url,body,token=props.token)=>api('/api/wallet-management'+url,{token,method:'POST',body:JSON.stringify(body)})
const labels=computed(()=>({checking:tr('Проверяем посты','Postlar tekshirilmoqda','Checking stations'),copying:tr('Копируем и сверяем данные','Ma’lumotlar ko‘chirilmoqda va tekshirilmoqda','Copying and checking data'),prepared:tr('Ожидаем подтверждения главного','Asosiy post tasdig‘i kutilmoqda','Waiting for the primary'),retiring:tr('Отключаем прежний резерв от роли','Eski zaxira roli olib tashlanmoqda','Retiring the old standby'),committing:tr('Сохраняем новые роли','Yangi rollar saqlanmoqda','Saving new roles'),activating:tr('Подтверждаем готовность','Tayyorlik tasdiqlanmoqda','Confirming readiness'),completed:tr('Изменение завершено','O‘zgarish yakunlandi','Change completed'),retired:tr('Роль резерва снята','Zaxira roli olib tashlandi','Standby role removed')}))
function selection(){return {kind:kind.value==='attach'?'replace_standby':kind.value,target_post:kind.value==='handover'?cfg.value.standby_post:Number(target.value),target_url:kind.value==='handover'?'':address.value,old_standby_fenced:fenced.value}}
function uuid(){const a=crypto.getRandomValues(new Uint8Array(16));a[6]=(a[6]&15)|64;a[8]=(a[8]&63)|128;return [...a].map((v,i)=>([4,6,8,10].includes(i)?'-':'')+v.toString(16).padStart(2,'0')).join('')}
async function load(){
 if(polling)return;polling=true
 try{
  const value=await request('/status');if(stopped)return
  data.value=value;emit('busy',Boolean(pending.value))
  if(observed&&value.operation?.request_id===observed&&['completed','aborted'].includes(value.operation.stage)){observed=null;kind.value='';emit('changed')}
 }finally{polling=false}
}
function failure(e){
 const messages={
 'Peer response authentication failed':['Пост не подтвердил подключение. Проверьте активацию и обновите участвующие посты.','Post ulanishni tasdiqlamadi. Faollashtirishni tekshiring va qatnashuvchi postlarni yangilang.','Station authentication failed. Check activation and update participating stations.'],
 'Wallet peer unavailable':['Пост недоступен. Проверьте питание и сеть.','Post mavjud emas. Quvvat va tarmoqni tekshiring.','Station unavailable. Check power and network.'],
 'Invalid credentials':['Неверный пароль. Повторите ввод.','Parol noto‘g‘ri. Qayta kiriting.','Incorrect password. Please try again.'],
 'Сначала завершите текущее изменение ролей':['Сначала завершите текущее изменение ролей.','Avval joriy rollar o‘zgarishini yakunlang.','Complete the current role change first.'],
 'Есть незавершённые операции':['Сначала завершите незавершённые операции кошелька.','Avval tugallanmagan hamyon amallarini yakunlang.','Finish outstanding wallet operations first.']
 }
 const text=messages[e.message];if(text)return tr(...text)
 if(props.language==='ru')return e.message
 return tr('Проверка не завершена. Проверьте настройки постов или обратитесь к установщику.','Tekshiruv yakunlanmadi. Post sozlamalarini tekshiring yoki o‘rnatuvchiga murojaat qiling.','Verification did not complete. Check station settings or contact your installer.')
}
async function run(fn){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=failure(e)}finally{busy.value=false}}
function choose(value){kind.value=value;preview.value=null;confirm.value=false;password.value='';error.value='';fenced.value=false;single.value=false;const n=Object.keys(cfg.value.peer_urls||{}).map(Number).find(n=>n!==cfg.value.primary_post&&n!==cfg.value.standby_post);target.value=n||[1,2,3,4].find(n=>n!==cfg.value.primary_post&&n!==cfg.value.standby_post);if(value==='attach')target.value=cfg.value.standby_post;address.value=cfg.value.peer_urls?.[String(target.value)]||''}
async function synchronize(){await post('/synchronize',{});notice.value=tr('Данные резерва проверены и синхронизированы.','Zaxira ma’lumotlari tekshirildi va sinxronlandi.','Standby data verified and synchronized.');await load();emit('changed')}
async function check(){preview.value=await post('/preview',selection());confirm.value=true}
async function submit(){
 const user=await api('/api/auth/me',{token:props.token})
 const auth=await login(user.login,password.value);password.value=''
 let response
 if(kind.value==='recover')response=await post('/recover',{old_primary_fenced:fenced.value,single_copy_accepted:single.value},auth.access_token)
 else if(kind.value==='cancel')response=await post('/cancel',{request_id:job.value.request_id},auth.access_token)
 else if(pending.value)response=await post('/resume',{request_id:job.value.request_id},auth.access_token)
 else response=await post('/change',{...selection(),request_id:uuid(),expected_authority:preview.value.before},auth.access_token)
 confirm.value=false
 if(kind.value==='recover'){kind.value='';notice.value=tr('Этот пост стал главным. Подключите резерв и проверьте синхронизацию.','Ushbu post asosiy bo‘ldi. Zaxirani ulang va sinxronlashni tekshiring.','This station is now primary. Connect the standby and verify synchronization.');emit('changed')}
 else if(kind.value==='cancel'){kind.value='';emit('changed')}
 else observed=response.operation.request_id
 await load()
}
onMounted(()=>{run(load);timer=setInterval(()=>{if(!document.hidden&&!busy.value)load().catch(()=>{})},2500)})
onUnmounted(()=>{stopped=true;clearInterval(timer);emit('busy',false)})
</script>
<template><section class="card post-management" aria-label="Посты и резервирование">
 <h2>{{tr('Посты и резервирование','Postlar va zaxiralash','Stations and redundancy')}}</h2>
 <p v-if="error" class="message error" role="alert">{{error}}</p><p v-if="notice" class="message success" role="status">{{notice}}</p>
 <template v-if="data">
 <div class="role-map"><div><span>{{tr('Главный','Asosiy','Primary')}}</span><strong>{{tr('Пост','Post','Station')}} {{cfg.primary_post}}</strong><b class="role-live" :class="liveClass(cfg.primary_post)">{{live(cfg.primary_post)}}</b><small>{{tr('Хранит общий кошелёк и управляет мойкой','Umumiy hamyonni saqlaydi va yuvishni boshqaradi','Stores the shared wallet and manages the site')}}</small></div><span class="role-arrow" aria-hidden="true">⇄</span><div><span>{{tr('Резерв','Zaxira','Standby')}}</span><strong>{{tr('Пост','Post','Station')}} {{cfg.standby_post}}</strong><b class="role-live" :class="liveClass(cfg.standby_post)">{{live(cfg.standby_post)}}</b><small>{{cfg.standby_ready?tr('Данные подтверждены при последней синхронизации','Oxirgi sinxronlashda ma’lumotlar tasdiqlangan','Data verified at the last synchronization'):tr('Готовность ещё не подтверждена','Tayyorlik hali tasdiqlanmagan','Readiness has not been verified')}}</small></div></div>
 <p v-if="cfg.single_node" class="message warning">{{tr('Сейчас работает одна серверная копия. Восстановите резервирование.','Hozir bitta server nusxasi ishlamoqda. Zaxiralashni tiklang.','There is currently one server copy. Restore standby replication.')}}</p>
 <p v-if="data.unconfigured_device_posts?.length" class="message warning">{{tr('Укажите тип новых постов в разделе «Кошелёк, бонусы и диагностика»: ','«Hamyon, bonuslar va diagnostika» bo‘limida yangi postlar turini belgilang: ','Set new station types under Wallet, bonuses and diagnostics: ')}} {{data.unconfigured_device_posts.join(', ')}}</p>
 <p>{{tr('Одновременно используется один главный и один резервный пост. Остальные посты работают как обычные.','Bir vaqtning o‘zida bitta asosiy va bitta zaxira ishlaydi. Boshqa postlar oddiy post sifatida ishlaydi.','One primary and one standby are used at a time. Other stations continue as ordinary stations.')}}</p>
 <div v-if="pending" class="role-progress" role="status">
  <h3>{{labels[job.stage]||tr('Изменение ролей','Rollarni o‘zgartirish','Changing roles')}}</h3>
  <p>{{tr('На время изменения операции общего кошелька приостановлены. Деньги и история сохраняются.','O‘zgarish vaqtida umumiy hamyon amallari to‘xtatilgan. Pul va tarix saqlanadi.','Shared wallet operations are paused during the change. Money and history are retained.')}}</p>
  <p v-if="job.error_code==='old_standby_online'" class="message error">{{tr('Прежний резерв всё ещё отвечает. Физически отключите его и продолжите проверку.','Eski zaxira hali javob bermoqda. Uni jismonan uzib, tekshiruvni davom ettiring.','The former standby is still responding. Physically disconnect it, then continue verification.')}}</p>
  <p v-else-if="job.error||(!data.running&&origin)" class="message error">{{tr('Связь или проверка не подтверждена. Проверьте посты и продолжите эту же операцию. Сброс не требуется.','Aloqa yoki tekshiruv tasdiqlanmadi. Postlarni tekshirib, shu amalni davom ettiring. Tiklash talab qilinmaydi.','Connection or verification is incomplete. Check the stations and continue this operation. No reset is needed.')}}</p>
  <button v-if="origin" class="primary" :disabled="busy||data.running" @click="kind='';confirm=true">{{tr('Продолжить проверку','Tekshiruvni davom ettirish','Continue verification')}}</button>
  <button v-if="origin&&!data.running&&['checking','copying'].includes(job.stage)" class="quiet" :disabled="busy" @click="kind='cancel';confirm=true">{{tr('Отменить изменение','O‘zgarishni bekor qilish','Cancel change')}}</button>
  <p v-if="!origin">{{tr('Продолжите на посту, где начали изменение.','O‘zgarish boshlangan postda davom eting.','Continue on the station where the change started.')}} <StationLink :href="cfg.peer_urls?.[String(job.before.primary_post)]+'/owner/wallet'" :language="language">{{tr('Открыть исходный пост','Boshlang‘ich postni ochish','Open originating station')}}</StationLink></p>
 </div>
 <template v-else>
  <p v-if="job?.stage==='aborted'" class="message success">{{tr('Изменение отменено. Прежние роли сохранены.','O‘zgarish bekor qilindi. Avvalgi rollar saqlandi.','Change cancelled. Previous roles retained.')}}</p>
  <p v-if="job?.stage==='completed'" class="message success">{{tr('Новые роли подтверждены.','Yangi rollar tasdiqlangan.','New roles confirmed.')}}</p>
  <p v-if="job?.old_standby_fenced" class="message warning">{{tr('Прежний резерв должен оставаться отключённым до повторного подключения установщиком.','Eski zaxira o‘rnatuvchi qayta ulaguncha o‘chiq qolishi kerak.','Keep the former standby disconnected until an installer rejoins it.')}}</p>
  <div v-if="primary" class="role-actions">
   <button v-if="!cfg.standby_ready&&!cfg.single_node" class="primary" :disabled="busy||disabled" @click="choose('attach')">{{tr('Подключить резерв','Zaxirani ulash','Connect standby')}}</button>
   <button class="quiet" :disabled="busy||disabled" @click="run(synchronize)">{{tr('Синхронизировать резерв','Zaxirani sinxronlash','Synchronize standby')}}</button>
   <button class="quiet" :disabled="busy||disabled" @click="choose('replace_standby')">{{tr('Заменить резерв','Zaxirani almashtirish','Replace standby')}}</button>
   <button class="quiet" :disabled="busy||disabled||!cfg.standby_ready" @click="choose('handover')">{{tr('Передать управление','Boshqaruvni topshirish','Transfer control')}}</button>
  </div>
  <template v-else><p>{{tr('Плановые изменения выполняются на главном посту.','Rejali o‘zgarishlar asosiy postda bajariladi.','Planned changes are performed on the primary station.')}}</p><StationLink :href="cfg.peer_urls?.[String(cfg.primary_post)]+'/owner'" :language="language">{{tr('Открыть главный пост','Asosiy postni ochish','Open primary station')}}</StationLink></template>
  <details v-if="standby" class="emergency"><summary>{{tr('Главный пост неисправен?','Asosiy post ishlamayaptimi?','Primary station has failed?')}}</summary><p>{{tr('Сначала физически отключите прежний главный от сети или питания. Одной ошибки связи недостаточно.','Avval eski asosiy postni tarmoqdan yoki quvvatdan uzing. Faqat aloqa xatosi yetarli emas.','First physically disconnect the former primary from power or the network. A connection error alone is not sufficient.')}}</p><p v-if="!cfg.standby_ready">{{tr('Этот резерв ещё не готов к восстановлению: сначала нужна полная синхронизация на главном.','Bu zaxira hali tiklashga tayyor emas: avval asosiy postda to‘liq sinxronlash kerak.','This standby is not ready for recovery: a full synchronization on the primary is required first.')}}</p><button class="quiet" :disabled="busy||disabled||!cfg.standby_ready" @click="choose('recover')">{{tr('Восстановить работу на этом посту','Ushbu postda ishni tiklash','Restore service on this station')}}</button></details>
  <form v-if="kind" class="role-form" @submit.prevent="run(kind==='recover'?async()=>{confirm=true}:check)">
   <h3>{{['replace_standby','attach'].includes(kind)?tr('Новый резервный пост','Yangi zaxira post','New standby station'):kind==='handover'?tr('Плановая передача управления','Boshqaruvni rejali topshirish','Planned control transfer'):tr('Аварийное восстановление','Favqulodda tiklash','Emergency recovery')}}</h3>
   <template v-if="['replace_standby','attach'].includes(kind)"><label>{{tr('Номер нового резервного поста','Yangi zaxira post raqami','New standby station number')}}<input v-model.number="target" type="number" min="1" max="100" @input="preview=null"/></label><PeerAddress v-model="address" :post="target" :context="network" :language="language" @update:model-value="preview=null"/><label v-if="kind!=='attach'" class="check"><input v-model="fenced" type="checkbox"/>{{tr('Прежний резерв неисправен и физически отключён. Он останется отключённым до повторного подключения установщиком.','Eski zaxira nosoz va jismonan uzilgan. O‘rnatuvchi qayta ulaguncha u o‘chiq qoladi.','The former standby has failed and is physically disconnected. It will stay disconnected until an installer rejoins it.')}}</label><p>{{tr('Главный останется прежним. Данные будут скопированы и проверены перед включением нового резерва.','Asosiy post o‘zgarmaydi. Yangi zaxira yoqilishidan oldin ma’lumotlar ko‘chiriladi va tekshiriladi.','The primary stays the same. Data will be copied and checked before enabling the new standby.')}}</p></template>
   <p v-if="kind==='handover'">{{tr('Пост','Post','Station')}} {{cfg.standby_post}} {{tr('станет главным, а нынешний главный — резервным. Оба поста должны быть доступны.','asosiy bo‘ladi, hozirgi asosiy esa zaxira bo‘ladi. Ikkala post ham mavjud bo‘lishi kerak.','will become primary; the current primary becomes standby. Both stations must be available.')}}</p>
   <template v-if="kind==='recover'"><label class="check"><input v-model="fenced" type="checkbox" required/>{{tr('Прежний главный физически отключён','Eski asosiy post jismonan uzilgan','Former primary is physically disconnected')}}</label><label class="check"><input v-model="single" type="checkbox" required/>{{tr('Понимаю: до восстановления резерва данные будут храниться на одном серверном посту','Tushunaman: zaxira tiklanguncha ma’lumotlar bitta server postida saqlanadi','I understand: until the standby is restored, there will be one server copy')}}</label></template>
   <div class="actions"><button class="quiet" type="button" :disabled="busy" @click="kind=''">{{tr('Отмена','Bekor qilish','Cancel')}}</button><button class="primary" :disabled="busy||disabled||(kind==='recover'&&(!fenced||!single))">{{tr('Проверить и продолжить','Tekshirish va davom etish','Check and continue')}}</button></div>
  </form>
 </template>
 </template>
 <Teleport to="body"><div v-if="confirm" class="confirm-backdrop"><form class="card role-confirm" role="dialog" aria-modal="true" :aria-label="tr('Подтверждение изменения ролей','Rollar o‘zgarishini tasdiqlash','Confirm role change')" @submit.prevent="run(submit)">
  <h2>{{tr('Подтвердите действие','Amalni tasdiqlang','Confirm the action')}}</h2>
  <p v-if="kind==='cancel'">{{tr('Изменение будет отменено. Прежние роли и все данные сохранятся.','O‘zgarish bekor qilinadi. Avvalgi rollar va barcha ma’lumotlar saqlanadi.','The change will be cancelled. Previous roles and all data will be retained.')}}</p>
  <p v-else-if="preview">{{tr('После изменения: главный — пост','O‘zgarishdan so‘ng: asosiy post','After the change: primary station')}} {{preview.after.primary_post}}, {{tr('резерв — пост','zaxira post','standby station')}} {{preview.after.standby_post}}.</p>
  <p>{{tr('Введите пароль вашей учётной записи. Деньги, карты и история не удаляются.','Hisobingiz parolini kiriting. Pul, kartalar va tarix o‘chirilmaydi.','Enter your account password. Money, cards and history will be retained.')}}</p>
  <p v-if="error" class="message error" role="alert">{{error}}</p>
  <label>{{tr('Пароль','Parol','Password')}}<input v-model="password" type="password" autocomplete="current-password" required/></label>
  <div class="actions"><button class="quiet" type="button" :disabled="busy" @click="confirm=false;password=''">{{tr('Отмена','Bekor qilish','Cancel')}}</button><button class="primary" :disabled="busy||!password">{{tr('Подтвердить','Tasdiqlash','Confirm')}}</button></div>
 </form></div></Teleport>
</section></template>
<style scoped>
.post-management{margin:24px 0;padding:24px;border:1px solid var(--border);border-radius:12px}.post-management p{line-height:1.6}.role-map{display:flex;gap:20px;align-items:center;margin:24px 0}.role-map>div{flex:1;background:var(--raised);border:1px solid var(--border);border-radius:10px;padding:20px;display:grid;gap:10px}.role-live{font-size:14px;font-weight:500;color:var(--muted)}.role-live.available{color:#16724b}.role-live.unavailable,.role-live.mismatch{color:#b05b18}.role-map strong{font-size:24px}.role-map small{line-height:1.5}.role-arrow{font-size:28px}.role-actions,.actions{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}.role-form,.role-progress,.emergency{border-top:1px solid var(--border);margin-top:24px;padding-top:24px}.role-form>label:not(.check){display:grid;gap:10px;max-width:420px;margin:20px 0}.check{display:flex;align-items:flex-start;gap:12px;line-height:1.6;margin:20px 0}.check input{flex:0 0 auto;margin-top:5px}.role-confirm{width:min(620px,94vw);max-height:90vh;overflow:auto;padding:28px}.role-confirm label{display:grid;gap:10px}.emergency summary{cursor:pointer;padding:12px 0;font-weight:600}@media(max-width:650px){.role-map{flex-direction:column;align-items:stretch}.role-arrow{text-align:center}.post-management{padding:16px}}
</style>
