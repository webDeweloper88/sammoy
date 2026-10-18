<script setup>
import { editPaymentAmount } from './payment-amount.js'
import { walletErrorText } from './card-feedback.js'
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import QrcodeVue from 'qrcode.vue'
import WashIcon from './WashIcon.vue'
import { api } from '../api.js'
const props=defineProps({preview:Boolean,open:Boolean,t:Object,ready:Boolean,state:Object,config:Object,options:Object})
const emit=defineEmits(['close','pending','preview-credit'])
const dialog=ref(null),method=ref(''),amount=ref('10000'),intent=ref(null),busy=ref(false),failed=ref(false),uncertain=ref(false),pollFailed=ref(false)
let timer,successTimer,stopped=false,startBills=0,intentVersion=0
const titleParts=computed(()=>{const at=props.t.topup.lastIndexOf(' ');return [props.t.topup.slice(0,at),props.t.topup.slice(at+1)]})
const isVip=computed(()=>props.state?.activeSessionSource==='vip')
const formattedBalance=computed(()=>isVip.value?'VIP':Number.isFinite(props.state?.creditSum)?props.state.creditSum.toLocaleString('ru-RU'):'—')
const startRfid=ref(null)
const cardResult=computed(()=>props.state?.lastRfidProcessedAt!==startRfid.value ? props.state?.lastRfidResult : null)
const replaceAmount=ref(true)
function chooseAmount(value){amount.value=String(value);replaceAmount.value=true}
const key='labrix-click-intent'
const terminal=['credited','cancelled','expired','error']
const pending=computed(()=>busy.value||uncertain.value||Boolean(intent.value&&!terminal.includes(intent.value.status)))
const clickReady=computed(()=>!isVip.value&&props.ready&&props.options?.click?.enabled===true&&props.state?.internetOnline===true)
const min=computed(()=>Math.max(props.config?.payment?.minAmount||1000,props.options?.click?.minAmount||1000))
const max=computed(()=>Math.min(props.config?.payment?.maxAmount||9999999,props.options?.click?.maxAmount||9999999))
const validAmount=computed(()=>/^\d+$/.test(amount.value)&&Number.isSafeInteger(Number(amount.value))&&Number(amount.value)>=min.value&&Number(amount.value)<=max.value)
const quickAmounts=computed(()=>(props.config?.payment?.quickAmounts||[5000,10000,20000]).filter(v=>v>=min.value&&v<=max.value))
const qrUrl=computed(()=>{try{const url=new URL(intent.value?.payment_url);return ['https:','http:'].includes(url.protocol)?url.href:''}catch{return ''}})
function save(){if(props.preview)return;try{if(uncertain.value)sessionStorage.setItem(key,JSON.stringify({unknown:true}));else if(intent.value&&!terminal.includes(intent.value.status))sessionStorage.setItem(key,JSON.stringify({id:intent.value.id}));else sessionStorage.removeItem(key)}catch{/* storage is optional during an active page */}}
watch(pending,v=>emit('pending',v),{immediate:true})
watch(()=>props.open,v=>{if(v){startBills=props.state?.billPulses||0;startRfid.value=props.state?.lastRfidProcessedAt;if(intent.value&&terminal.includes(intent.value.status))intent.value=null;method.value=intent.value||uncertain.value?'qr':'';dialog.value?.showModal()}else dialog.value?.close()})
watch(()=>props.state,s=>{
 if(!props.open||!s)return
 if(method.value==='cash'&&props.ready&&s.creditSum>0&&s.billPulses>startBills)emit('close')

},{deep:true})
watch(method,v=>{if(v==='qr')replaceAmount.value=true;if(v==='cash')startBills=props.state?.billPulses||0;if(v==='card')startRfid.value=props.state?.lastRfidProcessedAt})
function receive(data){
 const previous=intent.value?.status
 intent.value=data.intent;uncertain.value=false;pollFailed.value=false;save()
 if(intent.value?.status==='credited'&&previous!=='credited'&&!["wallet","recovery"].includes(intent.value.credit_destination)){
  clearTimeout(successTimer)
  successTimer=setTimeout(()=>{if(props.open&&method.value==='qr'&&intent.value?.status==='credited'&&props.ready)emit('close')},1400)
 }
}
async function poll(){
 if(stopped||props.preview)return
 if(intent.value?.id&&!terminal.includes(intent.value.status)&&!busy.value){
  const version=intentVersion,id=intent.value.id
  try{const data=await api('/api/click/intents/'+encodeURIComponent(id),{signal:AbortSignal.timeout(12000)});if(!stopped&&version===intentVersion&&id===intent.value?.id&&!busy.value)receive(data)}catch{if(!stopped&&version===intentVersion)pollFailed.value=true}
 }
 if(!stopped)timer=setTimeout(poll,2000)
}
async function create(){
 if(props.preview){if(validAmount.value&&!pending.value)receive({intent:{id:'preview-payment',amount_sum:Number(amount.value),status:'pending',payment_url:'https://labrixwash.invalid/demo-payment'}});return}
 if(busy.value||pending.value||!validAmount.value||!clickReady.value)return
 intentVersion++;busy.value=true;failed.value=false;uncertain.value=true;save()
 try{receive(await api('/api/click/intents',{method:'POST',body:JSON.stringify({amount_sum:Number(amount.value)}),signal:AbortSignal.timeout(15000)}))}
 catch(e){failed.value=true;if([400,409,423].includes(e.status)){uncertain.value=false;save()}}
 finally{intentVersion++;busy.value=false}
}
async function cancel(){
 if(props.preview){receive({intent:{...intent.value,status:'cancelled'}});return}
 if(busy.value||!intent.value?.id||!['local_pending','pending'].includes(intent.value.status))return
 intentVersion++;busy.value=true;failed.value=false
 try{receive(await api('/api/click/intents/'+encodeURIComponent(intent.value.id)+'/cancel',{method:'POST',signal:AbortSignal.timeout(15000)}))}catch{failed.value=true;pollFailed.value=true}finally{intentVersion++;busy.value=false}
}
function digit(k){const next=editPaymentAmount(amount.value,k,replaceAmount.value);amount.value=next.amount;replaceAmount.value=next.replace}
onMounted(()=>{
 if(props.preview)return
 try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved?.id)intent.value={id:saved.id,status:'pending'};else if(saved?.unknown)uncertain.value=true}catch{}
 poll()
})
onUnmounted(()=>{stopped=true;clearTimeout(timer);clearTimeout(successTimer)})
</script>
<template>
 <dialog ref="dialog" class="wash-dialog payment-dialog" @cancel.prevent="emit('close')" @close="emit('close')">
  <header class="payment-heading"><h2>{{ titleParts[0] }} <span>{{ titleParts[1] }}</span></h2><p>{{ t.choosePayment }}</p><button :aria-label="t.close" @click="emit('close')"><WashIcon name="close"/></button></header>
  <div class="payment-body"><p v-if="preview" role="status">DEMO · Тестовая оплата</p>
   <section class="payment-current-balance"><WashIcon name="coins"/><span>{{ t.currentBalance }}:</span><strong>{{ formattedBalance }} <small v-if="!isVip">so‘m</small></strong></section>
   <p v-if="isVip" class="payment-vip-note" role="status">{{t.vipPaymentHint}}</p>
   <div v-if="!method" class="payment-methods">
    <button class="payment-method payment-method-cash" :aria-label="t.cash" :disabled="!ready||isVip" @click="method='cash'"><WashIcon name="cash"/><span><strong>{{ t.cash }}</strong><small>{{ isVip?t.vipPaymentBlocked:ready?t.cashShort:t.unavailable }}</small></span><b aria-hidden="true">›</b></button>
    <button class="payment-method payment-method-qr" :aria-label="t.qr" :disabled="!clickReady&&!pending" @click="method='qr'"><WashIcon name="qr"/><span><strong>{{ t.qr }}</strong><small>{{ pending?t.pendingQr:isVip?t.vipPaymentBlocked:clickReady?'Click':t.unavailable }}</small></span><b aria-hidden="true">›</b></button>
    <button class="payment-method payment-method-card" :aria-label="t.card" :disabled="!ready || state?.lastRfidStatus==='offline' || state?.lastRfidStatus==='not_checked'" @click="method='card'"><WashIcon name="card"/><span><strong>{{ t.card }}</strong><small>{{ t.cardShort }}</small></span><b aria-hidden="true">›</b></button>
   </div>
   <template v-else-if="method==='cash'||method==='card'">
    <WashIcon class="payment-large-icon" :name="method"/>
    <h3>{{ t[method] }}</h3><p>{{ method==='cash'?t.cashHint:(state?.creditSum>0?t.cardSave:t.cardHint) }}</p>
    <p v-if="method==='card' && cardResult" role="status">{{ cardResult==='wallet_error'?walletErrorText(state,t):cardResult==='card_in_use'?t.cardInUse:cardResult==='vip_granted'?t.vipGranted:cardResult==='customer_balance_used'?t.cardLoaded:cardResult==='customer_balance_saved'?t.cardSaved:['vip_remaining_burned','vip_session_closed'].includes(cardResult)?t.cardClosed:t.cardRejected }}</p>
    <button v-if="preview" class="sheet-action" @click="emit('preview-credit',5000);emit('close')">Тест: +5 000 so‘m</button>
    <p v-if="!ready" class="payment-error">{{ t.hardware }}</p>
   </template>
   <template v-else>
    <template v-if="uncertain"><p role="alert" class="payment-error">{{ busy?t.processing:t.qrUnknown }}</p></template>
    <template v-else-if="intent">
     <h3>{{ Number(intent.amount_sum||amount).toLocaleString('ru-RU') }} so‘m</h3>
     <p v-if="intent.status==='credited'" role="status">{{ intent.credit_destination==='wallet'?t.walletCredited:intent.credit_destination==='recovery'?t.paymentRecovery:t.credited }}</p>
     <p v-else-if="terminal.includes(intent.status)">{{ t.expired }}</p>
     <template v-else>
      <QrcodeVue v-if="qrUrl" :value="qrUrl" :size="360" level="M" render-as="svg" class="payment-qr" :aria-label="t.scan"/>
      <p>{{ preview?'DEMO · QR не для оплаты':qrUrl?t.scan:t.processing }}</p><button v-if="preview" class="sheet-action" @click="emit('preview-credit',intent.amount_sum);receive({intent:{...intent,status:'credited'}})">Тест: подтвердить оплату</button><p>{{ intent.status==='paid'||intent.status==='prepared'?t.processing:t.waiting }}</p>
      <p v-if="pollFailed" role="alert" class="payment-error">{{ t.qrUnknown }}</p>
      <button class="sheet-action" :disabled="busy||!['local_pending','pending'].includes(intent.status)" @click="cancel">{{ t.cancel }}</button>
     </template>
     <button v-if="terminal.includes(intent.status)" class="sheet-action" @click="intent=null">{{ t.back }}</button>
    </template>
    <template v-else>
     <label class="payment-amount">{{ t.amount }} <output>{{ amount||'0' }} so‘m</output></label>
     <div class="payment-quick"><button v-for="v in quickAmounts" :key="v" @click="chooseAmount(v)">{{ v.toLocaleString('ru-RU') }}</button></div>
     <div class="payment-keypad"><button v-for="k in ['1','2','3','4','5','6','7','8','9','C','0','⌫']" :key="k" @click="digit(k)">{{ k }}</button></div>
     <p class="payment-limits">{{ min.toLocaleString('ru-RU') }} – {{ max.toLocaleString('ru-RU') }} so‘m</p>
     <button class="sheet-action primary-action" :disabled="!validAmount||!clickReady||busy" @click="create">{{ t.createQr }}</button>
    </template>
    <p v-if="failed&&!uncertain" class="payment-error" role="alert">{{ t.failed }}</p>
   </template>
   <button v-if="method" class="sheet-action" @click="method=''">{{ t.back }}</button>
   <button v-else class="sheet-action payment-close" @click="emit('close')">{{ t.close }}</button>
  </div>
 </dialog>
</template>
