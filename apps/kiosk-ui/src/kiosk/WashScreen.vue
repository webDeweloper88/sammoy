<script setup>
import {dryFogIds,dryFogAdditional,dryFogLabels,dryFogDescriptions,dryFogTones,dryFogTexts} from './dry-fog.js'
import { walletErrorText } from './card-feedback.js'
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import {modePhoto} from './theme2-media.js'
import ProgramCards from './ProgramCards.vue'
import './cards.css'
import ProgramWheel from './ProgramWheel.vue'
import {lightTones,darkTones,darkActiveTones,programInk,readableInk} from './program-tones.js'
import WashIcon from './WashIcon.vue'
import WashFooter from './WashFooter.vue'
import IdleScreen from './IdleScreen.vue'
import PaymentSheet from './PaymentSheet.vue'
import { useWashPreview } from './useWashPreview.js'
import { useWashState } from './useWashState.js'
import { useIdleScreen } from './useIdleScreen.js'
import { washTexts,programLabels,programDescriptions,localized } from './wash-texts.js'
import { languageNames } from './idle-texts.js'
import './wash.css'
import './light.css'
import './wheel-status.css'
import {brandTitle,brandSubtitle,defaultLanguage} from './presentation.js'
import { resolveAppearance } from './appearance.js'
const props=defineProps({preview:{type:Boolean,default:false},previewKind:{type:String,default:'wash'}})
const runtime=props.preview?useWashPreview(props.previewKind):useWashState()
const language=ref('uz'),paymentOpen=ref(false),paymentPending=ref(false),socialOpen=ref(false)
const {state,parameters,config,paymentOptions,station,receivedAt,now,fresh,ready,busy,error,select}=runtime
if(props.preview){const demo=new URLSearchParams(window.location.search);if(demo.get('design')==='cards')config.value.theme.design='cards';if(['light','dark'].includes(demo.get('theme')))config.value.theme.appearance.manualTheme=demo.get('theme')}
const lastAppearance=ref(null)
let initialLanguageApplied=false
watch(config,c=>{if(c&&!initialLanguageApplied){language.value=defaultLanguage(c);initialLanguageApplied=true}},{immediate:true})
watch(config,c=>{if(c?.theme?.appearance)lastAppearance.value=c.theme.appearance},{immediate:true})
const design=computed(()=>config.value?.theme?.design==='wheel'?'wheel':'cards')
const appearance=computed(()=>resolveAppearance(lastAppearance.value,new Date(now.value)))
const dryFog=computed(()=>props.preview?props.previewKind==='dry_fog':state.value?.deviceType==='dry_fog')
const idleBlocked=computed(()=>paymentOpen.value||paymentPending.value||socialOpen.value||props.preview||dryFog.value)
const {visible:idleVisible,wake}=useIdleScreen(state,receivedAt,idleBlocked)
const t=computed(()=>({...washTexts[language.value],...(dryFog.value?dryFogTexts[language.value]:{})}))
const credit=computed(()=>state.value?.creditSum)
const selected=computed(()=>state.value?.activeMode||state.value?.armedMode)
const manualPause=computed(()=>state.value?.selectedMode==='pause'&&Boolean(state.value?.armedMode))
const running=computed(()=>state.value?.phase==='active'&&!!state.value?.activeMode)
const paused=computed(()=>!!selected.value&&!running.value&&(manualPause.value||state.value?.pauseState!=='none'||state.value?.phase?.startsWith('trigger_')))
const pauseVisual=computed(()=>!fresh.value||!ready.value?'none':state.value?.pauseState==='free'?'free':state.value?.pauseState==='paid'?'paid':state.value?.phase==='pause_free_exhausted'?'stopped':'none')
const timePrimary=computed(()=>running.value||paused.value)
const statusText=computed(()=>{
 const s=state.value
 if(!fresh.value)return t.value.offline
 if(s?.softwareUpdateJob)return t.value.softwareUpdating
 if(s?.licenseLocked)return t.value.locked
 if(s?.walletTransferPending)return s.walletOperationInProgress ? t.value.walletProcessing : t.value.walletPending
 if(!ready.value)return t.value.hardware
 if(error.value)return t.value.failed
 if(s?.purgeActive)return t.value.purgeRunning
 if(s?.walletCashHeld>0)return t.value.cashHeld+' · '+Number(s.walletCashHeld).toLocaleString('ru-RU')+' so‘m'
 if(s?.lastRfidProcessedAt&&now.value-Date.parse(s.lastRfidProcessedAt)>=0&&now.value-Date.parse(s.lastRfidProcessedAt)<8000){
  const result=s.lastRfidResult
  if(result==='nfc_unsupported')return t.value.nfcUnsupported
  if(result==='wallet_error')return walletErrorText(s,t.value)
  if(result==='bonus_not_available_for_device')return t.value.bonusNotForDevice
  if(result==='card_in_use')return t.value.cardInUse
  if(result==='vip_granted')return t.value.vipGranted
  if(result==='vip_session_closed')return t.value.cardClosed
  if(Number.isFinite(s.walletLastAmount)&&['customer_balance_used','customer_balance_saved'].includes(result))return (result==='customer_balance_used'?t.value.cardLoaded:t.value.cardSaved)+' · '+s.walletLastAmount.toLocaleString('ru-RU')+' so‘m'
 }
 if(s?.resumeRequiresTriggerReset)return t.value.release
 if(s?.powerRecoveryAvailable)return t.value.recovered
 if(s?.pauseState==='free')return t.value.freePause+' · '+(manualPause.value?t.value.resume:t.value.trigger)
 if(s?.pauseState==='paid')return (isVip.value?t.value.vipPauseCharging:t.value.pauseCharging)+' · '+(manualPause.value?t.value.resume:t.value.trigger)
 if(s?.phase==='pause_free_exhausted')return t.value.pauseStopped
 if(running.value)return t.value.running
 if(selected.value)return t.value.trigger
 return credit.value>0?t.value.choose:t.value.addMoney
})
const timerLabel=computed(()=>state.value?.displayTimeKind==='free_pause'?t.value.freePause:state.value?.displayTimeKind==='paid_pause'?t.value.paidPause:t.value.time)
const time=computed(()=>{
 const n=state.value?.remainingSeconds
 if(!fresh.value||!Number.isFinite(n))return '—:—'
 const seconds=Math.max(0,Math.ceil(n));return String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0')
})
const isVip=computed(()=>state.value?.activeSessionSource==='vip')
const balance=computed(()=>isVip.value?'VIP':fresh.value&&Number.isFinite(credit.value)?credit.value.toLocaleString('ru-RU'):'—')
const programs=computed(()=>(dryFog.value?dryFogIds:['foam','wax','osmos','nano','chem','water','air','vacuum']).filter(id=>parameters.value?.tariffs?.[id]?.enabled===true&&config.value?.programs?.some(p=>p.id===id&&p.visible!==false)).map(id=>{
 const entry=config.value.programs.find(p=>p.id===id)
 return {id,label:entry?.label?.[language.value]||localized((dryFog.value?dryFogLabels:programLabels)[id],language.value),description:typeof entry?.description?.[language.value]==='string'?entry.description[language.value]:localized((dryFog.value?dryFogDescriptions:programDescriptions)[id],language.value)}
}))
const mainPrograms=computed(()=>programs.value.filter(p=>!(dryFog.value?dryFogAdditional:['air','vacuum']).includes(p.id)))
const activeProgram=computed(()=>programs.value.find(p=>p.id===selected.value))
const activeTone=computed(()=>dryFog.value?dryFogTones[selected.value]||'#008dce':design.value==='cards'?({water:'#008dce',foam:'#db0062',wax:'#a96a00',chem:'#268237',osmos:'#0087ad',nano:'#7441ce',air:'#008caa',vacuum:'#5865c9'}[selected.value]||'#008dce'):(appearance.value==='light'?lightTones:darkActiveTones)[selected.value]||'#39c7ef')
const cardStatusKind=computed(()=>!fresh.value||!ready.value?'fault':pauseVisual.value!=='none'?pauseVisual.value:running.value?'running':activeProgram.value?'waiting':'idle')
const cardStatusTitle=computed(()=>{
 if(cardStatusKind.value==='fault')return ''
 if(pauseVisual.value==='free')return t.value.freePause
 if(pauseVisual.value==='paid')return t.value.paidPause
 if(pauseVisual.value==='stopped')return t.value.pause
 return activeProgram.value?.label||(credit.value>0?t.value.choose:t.value.beginTitle)
})
const cardStatusIcon=computed(()=>pauseVisual.value!=='none'?'pause':activeProgram.value?.id||'wallet')
const cardStatusNote=computed(()=>{
 // Preserve card, safety and recovery notices instead of hiding them behind a short state label.
 const s=state.value
 if(!ready.value||error.value||s?.walletCashHeld>0||s?.resumeRequiresTriggerReset||s?.powerRecoveryAvailable||(s?.lastRfidProcessedAt&&now.value-Date.parse(s.lastRfidProcessedAt)>=0&&now.value-Date.parse(s.lastRfidProcessedAt)<8000))return statusText.value
 if(running.value&&statusText.value===t.value.running)return t.value.operatingShort
 if(pauseVisual.value==='free')return activeProgram.value?.label+' · '+(manualPause.value?t.value.resume:t.value.trigger)
 if(pauseVisual.value==='paid'){
  if(isVip.value)return t.value.vipPauseCharging
  const price=parameters.value?.paidPause
  return price?.amountSum>=0&&price?.durationSeconds>0?Number(price.amountSum).toLocaleString('ru-RU')+' so‘m / '+price.durationSeconds+' s':statusText.value
 }
 return statusText.value
})
const wheelStatusTone=computed(()=>activeProgram.value&&ready.value?activeTone.value:appearance.value==='light'?'#c6d9e6':'#263e50')
const wheelStatusInk=computed(()=>readableInk(wheelStatusTone.value,appearance.value))
const statusPhoto=computed(()=>modePhoto(selected.value||(dryFog.value?'aroma_1':'nano')))
const optionalPrograms=computed(()=>programs.value.filter(p=>(dryFog.value?dryFogAdditional:['air','vacuum']).includes(p.id)))
const centerLabel=computed(()=>!selected.value?t.value.choose:manualPause.value?t.value.resume:t.value.pause)
const centerSub=computed(()=>state.value?.resumeRequiresTriggerReset?t.value.release:pauseVisual.value==='free'?t.value.freePause:pauseVisual.value==='paid'?t.value.paidPause:pauseVisual.value==='stopped'?t.value.noCharge:!selected.value?'':manualPause.value?'':t.value.pauseSub)
const cardCenterSub=computed(()=>{if(state.value?.resumeRequiresTriggerReset)return t.value.release;if(pauseVisual.value==='free')return t.value.freePause+' · '+time.value;if(pauseVisual.value==='paid'){if(isVip.value)return t.value.vipPauseCharging;const p=parameters.value?.paidPause;return t.value.paidPause+(p?.amountSum>=0&&p?.durationSeconds>0?' · '+Number(p.amountSum).toLocaleString('ru-RU')+' so‘m / '+p.durationSeconds+' s':'')}return centerSub.value})
const centerDisabled=computed(()=>!selected.value||(manualPause.value&&(!ready.value||state.value?.resumeRequiresTriggerReset)))
async function choose(id){if(!ready.value||busy.value)return;if(!(credit.value>0)){paymentOpen.value=true;return}await select(id)}
async function center(){if(busy.value||centerDisabled.value)return;if(manualPause.value)await select(state.value.armedMode);else await select('pause')}
let loginTimer=null,loginPoint=null
function cancelLoginHold(){clearTimeout(loginTimer);loginTimer=null;loginPoint=null}
function startLoginHold(event){if(event.type==='pointerdown'&&(!event.isPrimary||event.button!==0))return;if(loginTimer)return;loginPoint={x:event.clientX,y:event.clientY};loginTimer=setTimeout(()=>{cancelLoginHold();if(!props.preview)window.location.assign('/login')},6000)}
function moveLoginHold(event){if(loginPoint&&Math.hypot(event.clientX-loginPoint.x,event.clientY-loginPoint.y)>16)cancelLoginHold()}
function visibilityChanged(){if(document.hidden)cancelLoginHold()}
onMounted(()=>{window.addEventListener('blur',cancelLoginHold);document.addEventListener('visibilitychange',visibilityChanged)})
onUnmounted(()=>{cancelLoginHold();window.removeEventListener('blur',cancelLoginHold);document.removeEventListener('visibilitychange',visibilityChanged)})
watch(idleVisible, v=>{if(v)language.value=defaultLanguage(config.value)})
</script>
<template>
 <div class="wash-kiosk" :data-theme="appearance" :data-design="design">
 <details v-if="preview" class="preview-tools"><summary>DEMO · Настройки</summary><p>Тестовые данные · без оборудования</p><label>Состояние<select aria-label="Состояние" @change="runtime.scenario($event.target.value)"><option value="balance">Баланс 25 000</option><option value="active">Активная мойка</option><option value="free">Бесплатная пауза</option><option value="paid">Платная пауза</option><option value="empty">Нулевой баланс</option><option value="vip">VIP-допуск</option><option value="pending">Незавершённый перевод</option><option value="held">Наличные во время VIP</option></select></label><label v-if="!dryFog">Дизайн<select aria-label="Дизайн" v-model="config.theme.design"><option value="wheel">Круговой</option><option value="cards">Карточки</option></select></label><label>Вид<select aria-label="Вид" v-model="config.theme.appearance.manualTheme"><option value="dark">Dark</option><option value="light">Light</option></select></label><label v-for="id in (dryFog?dryFogAdditional:['air','vacuum'])" :key="id"><input v-model="config.programs.find(p=>p.id===id).visible" type="checkbox"/>{{dryFog?dryFogLabels[id][0]:id==='air'?'HAVO':'PLISOS'}}</label><button @click="runtime.addCredit(5000)">Тест: +5 000 so‘m</button></details>
 <IdleScreen v-if="idleVisible" :config="config" v-model:language="language" @wake="wake"/>
 <main v-else :aria-busy="busy" class="wash-screen" :class="{'without-optional':!optionalPrograms.length,'cards-design':design==='cards','dry-fog-design':dryFog}" :lang="{uz:'uz',kz:'kk',ky:'ky',ru:'ru'}[language]">
  <header class="wash-topbar">
   <div class="wash-brand" role="button" tabindex="0" :aria-label="t.admin" @pointerdown="startLoginHold" @pointerup="cancelLoginHold" @pointercancel="cancelLoginHold" @pointerleave="cancelLoginHold" @pointermove="moveLoginHold" @contextmenu.prevent @keydown.enter.prevent="startLoginHold" @keyup.enter="cancelLoginHold" @blur="cancelLoginHold"><img v-if="config?.brand?.logoUrl" class="wash-owner-logo" :src="config.brand.logoUrl" alt=""/><img v-else class="theme2-brand-mark" src="/assets/theme2/brand/labrix_mark_L.png" alt=""/><div><strong v-if="brandTitle(config)==='LABRIX WASH'">LABRIX <span>WASH</span></strong><strong v-else class="custom-brand">{{brandTitle(config)}}</strong><small>{{ brandSubtitle(config,t.descriptor) }}</small></div></div>
   <nav v-if="config?.layout?.showLanguageButtons!==false" aria-label="Language"><button v-for="lang in ['ru','uz','kz','ky']" :key="lang" :aria-label="languageNames[lang]" :aria-pressed="language===lang" :class="{active:language===lang}" @click="language=lang">{{ lang.toUpperCase() }}</button></nav>
  </header>
  <section class="wash-status" :style="design==='wheel'?{'--status-tone':wheelStatusTone,'--status-ink':wheelStatusInk}:undefined" :class="{'wheel-status':design==='wheel','time-primary':timePrimary,'pause-free':pauseVisual==='free','pause-paid':pauseVisual==='paid','pause-stopped':pauseVisual==='stopped'}" :aria-label="t.balance+' / '+t.time">
   <img v-if="design==='cards'" class="status-scene" :src="statusPhoto" alt="" decoding="async"/>
   <div class="status-primary" :class="{'has-bonus':!timePrimary&&!isVip&&fresh&&state?.bonusSum>0}">
    <span class="status-label">{{ timePrimary?timerLabel:t.balance }}</span>
    <div class="status-value"><WashIcon :name="timePrimary?'clock':'coins'"/><strong :style="{fontSize:!timePrimary&&balance.length>9?'calc(82 * var(--u))':undefined}">{{ timePrimary?time:balance }}</strong><span v-if="!timePrimary&&!isVip" class="currency">so‘m</span></div>
   <p v-if="!timePrimary&&!isVip&&fresh&&state?.bonusSum>0" class="bonus-caption">{{ language==='ru'?'Включая бонус':language==='kz'?'Бонус қоса есептелген':language==='ky'?'Бонус кошулган':'Shu jumladan bonus' }} {{ Number(state.bonusSum).toLocaleString('ru-RU') }} so‘m</p>
   </div>
   <p v-if="design==='cards'" class="wash-status-hint card-status-detail" :class="['state-'+cardStatusKind,{fault:!ready}]" :style="{'--active-tone':activeTone}" role="status">
    <template v-if="cardStatusTitle"><span class="card-status-eyebrow">{{cardStatusKind==='idle'?t.nextStep:t.currentProgram}}</span><WashIcon :name="cardStatusIcon"/><strong>{{cardStatusTitle}}</strong></template>
    <span class="card-status-note"><span v-if="cardStatusKind==='running'" class="card-status-dot" aria-hidden="true"></span>{{cardStatusNote}}</span>
   </p>
   <p v-else class="wash-status-hint" :class="{fault:!ready,'active-program-hint':ready&&!!activeProgram}" :style="{'--active-tone':activeTone}" role="status"><template v-if="ready&&activeProgram"><WashIcon :name="pauseVisual!=='none'?'pause':activeProgram.id"/><strong>{{ activeProgram.label }}</strong></template><span class="wheel-status-note">{{ statusText }}</span></p>

   <div class="status-secondary"><span>{{ timePrimary?t.balance:timerLabel }}</span><div><WashIcon :name="timePrimary?'coins':'clock'"/><strong>{{ timePrimary?balance:time }}</strong><small v-if="timePrimary&&!isVip">so‘m</small></div>   <p v-if="timePrimary&&!isVip&&fresh&&state?.bonusSum>0" class="bonus-caption">{{ language==='ru'?'Включая бонус':language==='kz'?'Бонус қоса есептелген':language==='ky'?'Бонус кошулган':'Shu jumladan bonus' }} {{ Number(state.bonusSum).toLocaleString('ru-RU') }} so‘m</p></div>
  </section>
  <ProgramCards :pause-enabled="!dryFog||parameters?.pauseEnabled!==false||manualPause" v-if="design==='cards'" :programs="mainPrograms" :selected="selected" :active="running" :disabled="!ready" :t="t" :heading="dryFog?t.aromaHeading:undefined" :language="language" :pause-state="pauseVisual" :center-label="!selected&&!(credit>0)?t.addMoney:centerLabel" :center-sub="cardCenterSub" :center-icon="!selected?(credit>0?'water':'wallet'):manualPause?'play':'pause'" :center-disabled="centerDisabled" @select="choose" @center="center"/>
  <section v-else class="wash-wheel-area">
   <ProgramWheel :running-label="t.runningBadge" :theme="appearance" :programs="mainPrograms" :selected="selected" :active="running" :pause-state="pauseVisual" :disabled="!ready" :center-label="centerLabel" :center-sub="centerSub" :center-icon="manualPause||!selected?'play':'pause'" :center-disabled="centerDisabled" @select="choose" @center="center"/>
  </section>
  <section v-if="optionalPrograms.length" class="wash-optional" :class="{'has-running-extra':dryFog&&running&&optionalPrograms.some(p=>p.id===selected)}">
   <h2>{{ t.optional }}</h2>
   <div><button v-for="p in optionalPrograms" :key="p.id" :data-program="p.id" :class="{selected:selected===p.id,running:running&&selected===p.id}" :style="{'--optional-tone':(dryFog?dryFogTones:appearance==='light'?lightTones:darkActiveTones)[p.id],'--optional-ink':programInk(appearance,p.id)}" :aria-label="p.label" :aria-pressed="selected===p.id" :disabled="!ready" @click="choose(p.id)"><img v-if="design==='cards'" class="mode-photo" :src="modePhoto(p.id)" alt="" decoding="async"/><WashIcon :name="p.id"/><span><strong :class="{'long-name':p.label.length>10}">{{ p.label }}</strong><small v-if="dryFog&&running&&selected===p.id" class="extra-active-badge"><span aria-hidden="true">✓</span> {{t.runningBadge}}</small><small v-else>{{ design==='cards' && selected===p.id ? (running?t.running:t.trigger) : p.description }}</small></span><b v-if="design!=='cards'" aria-hidden="true">{{selected===p.id?'✓':'+'}}</b><span v-else-if="running&&selected===p.id" class="mode-running-dot" aria-hidden="true"></span></button></div>
  </section>
  <button class="wash-topup" :aria-label="t.topup" :class="{emphasized:credit===0||paymentPending}" :disabled="!ready&&!paymentPending" @click="paymentOpen=true"><span><WashIcon name="wallet"/><span class="topup-title"><strong>{{design==='cards'&&!(credit>0)?t.readyToWash:t.topup}}</strong><small v-if="design==='cards'&&!(credit>0)">{{t.choosePayment}}</small></span><b aria-hidden="true">+</b></span><span class="topup-methods"><span><WashIcon name="cash"/>{{ t.cash }}</span><span><WashIcon name="qr"/>QR</span><span><WashIcon name="card"/>{{ t.card }}</span></span></button>
  <WashFooter :preview="preview" :contacts="config?.contacts" :station="station" :t="t" @open="socialOpen=$event"/>
 </main>
 <PaymentSheet :preview="preview" @preview-credit="runtime.addCredit($event)" :open="paymentOpen" :t="t" :state="state" :ready="ready" :config="config" :options="paymentOptions" @close="paymentOpen=false" @pending="paymentPending=$event"/>

 </div>
</template>

<style scoped>.theme2-brand-mark{width:calc(82 * var(--u));height:calc(90 * var(--u));object-fit:contain;flex:none}.preview-tools{position:fixed;top:8px;left:8px;z-index:50;background:#152733;color:white;border:1px solid #8eb5cb;border-radius:8px;font-family:Arial,sans-serif;font-size:16px;padding:10px;max-width:340px;box-shadow:0 3px 12px #0005}.preview-tools summary{cursor:pointer;font-weight:bold;min-height:32px}.preview-tools label{display:flex;gap:12px;align-items:center;justify-content:space-between;margin:12px 0}.preview-tools select,.preview-tools button{font-size:16px;padding:12px;border-radius:6px;border:1px solid #8eb5cb;background:#fff;color:#152733}.preview-tools p{font-size:14px}.preview-tools input{width:24px;height:24px}.status-primary.has-bonus .status-value strong{font-size:calc(104 * var(--u))}
</style>

<style scoped>.theme2-brand-mark{width:calc(82 * var(--u));height:calc(90 * var(--u));object-fit:contain;flex:none}
.bonus-caption{margin:0;text-align:center;font-size:calc(20 * var(--u));line-height:1.15;color:var(--wash-muted)}
.status-primary.has-bonus .status-value strong{font-size:calc(104 * var(--u))}
</style>

<style scoped>.theme2-brand-mark{width:calc(82 * var(--u));height:calc(90 * var(--u));object-fit:contain;flex:none}.wash-owner-logo{width:calc(70 * var(--u));height:calc(76 * var(--u));object-fit:contain}.wash-brand strong.custom-brand{white-space:normal;font-size:calc(38 * var(--u));max-width:calc(560 * var(--u));overflow-wrap:anywhere;line-height:1.1}</style>
