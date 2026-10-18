<script setup>
import {ref,computed,onMounted,onUnmounted} from 'vue'
import QrcodeVue from 'qrcode.vue'
import WashIcon from './WashIcon.vue'
import {api} from '../api.js'
const props=defineProps({contacts:Object,station:Object,t:Object,preview:Boolean})
const emit=defineEmits(['open'])
const devRefresh=import.meta.env.VITE_KIOSK_DEV_TOOLS==='true'
function reloadPage(){window.location.reload()}
const dialog=ref(null),kind=ref(''),selected=ref(null),call=ref(null),busy=ref(false),uncertain=ref(false),clock=ref(Date.now())
let timer,stopped=false
const operator=computed(()=>props.contacts?.operator||{enabled:false,phone:props.contacts?.supportPhone||''})
const manufacturer=computed(()=>props.contacts?.manufacturer||{})
const phone=computed(()=>operator.value.phone||'')
const post=computed(()=>Number.isInteger(props.station?.postNo)&&props.station.postNo>0?String(props.station.postNo).padStart(2,'0'):'—')
const accounts=[{id:'telegram',name:'Telegram',path:'m21 3-4 18-6-5-3 3 1-6 9-7-12 6-5-2Z'},{id:'instagram',name:'Instagram',path:'M8 3h8a5 5 0 0 1 5 5v8a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5V8a5 5 0 0 1 5-5Z M16 12a4 4 0 1 1-8 0a4 4 0 0 1 8 0 M17.5 6.5h.01'},{id:'youtube',name:'YouTube',path:'M6 5h12a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V9a4 4 0 0 1 4-4Z m4 4 6 3-6 3Z'}]
function url(id){try{const u=new URL(manufacturer.value[id]||props.contacts?.socialLinks?.[id]);return u.protocol==='https:'?u.href:''}catch{return ''}}
const socialAccounts=computed(()=>accounts.filter(a=>url(a.id)))
const title=computed(()=>kind.value==='operator'?props.t.operatorCall:kind.value==='service'?props.t.serviceContacts:selected.value?.name||'')
const callMessage=computed(()=>uncertain.value?props.t.callUnknown:call.value?.status==='sent'?props.t.callSent:['failed','expired','unavailable'].includes(call.value?.status)?props.t.callFailed:call.value?.status==='unknown'?props.t.callUnknown:props.t.callSending)
function open(kindValue,account=null){if(kindValue==='social'&&!url(account.id))return;selected.value=account;kind.value=kindValue;emit('open',true);dialog.value.showModal()}
function close(){dialog.value?.close();emit('open',false)}
const storageKey=computed(()=>'labrix-operator-call:'+post.value)
function save(){if(props.preview)return;try{sessionStorage.setItem(storageKey.value,JSON.stringify({call:call.value,uncertain:uncertain.value}))}catch{}}
function newCallId(){if(crypto.randomUUID)return crypto.randomUUID();const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;return [...b].map((v,i)=>([4,6,8,10].includes(i)?'-':'')+v.toString(16).padStart(2,'0')).join('')}
async function invoke(){
 open('operator')
 if(props.preview){call.value={status:'sent'};return}
 if(busy.value)return
 if(call.value?.status==='sent'&&clock.value<call.value.until)return
 if(!call.value||(!uncertain.value&&clock.value>call.value.until))call.value={request_id:newCallId(),status:'queued',until:Date.now()+120000}
 if(['queued','sending'].includes(call.value?.status)&&!uncertain.value&&call.value.accepted){await check();return}
 busy.value=true;uncertain.value=true;save()
 try{const data=await api('/api/kiosk/operator/call',{method:'POST',body:JSON.stringify({request_id:call.value.request_id}),signal:AbortSignal.timeout(12000)});call.value={...data,accepted:true,until:Date.now()+(data.retry_after||0)*1000};uncertain.value=false;save()}
 catch(e){if([400,401,403,409,422].includes(e.status)){uncertain.value=false;call.value={...call.value,status:'unavailable'};save()}}
 finally{busy.value=false}
}
async function check(){
 if(props.preview||busy.value||!call.value?.request_id)return
 busy.value=true
 try{const data=await api('/api/kiosk/operator/call/'+call.value.request_id,{signal:AbortSignal.timeout(10000)});call.value={...data,accepted:true,until:Date.now()+(data.retry_after||0)*1000};uncertain.value=false;save()}catch{uncertain.value=true;save()}finally{busy.value=false}
}
function telephone(value){return 'tel:'+value.replace(/[^+0-9]/g,'')}
onMounted(()=>{try{if(!props.preview){const saved=JSON.parse(sessionStorage.getItem(storageKey.value)||'null');if(saved?.call?.request_id){call.value=saved.call;uncertain.value=!!saved.uncertain}}}catch{}
 timer=setInterval(()=>{clock.value=Date.now();if(!stopped&&!document.hidden&&call.value?.accepted&&['queued','sending'].includes(call.value.status))check()},3000)
})
onUnmounted(()=>{stopped=true;clearInterval(timer)})
</script>
<template>
 <footer class="wash-footer wash-footer-service">
  <div class="footer-service-row"><span class="footer-post">POST {{post}}</span><button v-if="operator.enabled" class="footer-operator-button" @click="invoke"><WashIcon name="help"/><span>{{t.operatorCall}}</span></button><span v-if="phone" class="footer-phone"><WashIcon name="phone"/>{{phone}}</span><button v-if="devRefresh" class="footer-dev-refresh" type="button" aria-label="DEV: обновить страницу" @click="reloadPage">↻ DEV</button></div>
  <div class="footer-social-row"><span class="footer-manufacturer">{{t.manufacturer}}</span><button class="footer-service-button" @click="open('service')">{{t.serviceContacts}}</button><div class="footer-social-links"><button v-for="a in accounts" :key="a.id" :data-brand="a.id" :aria-label="a.name+' QR'" :disabled="!url(a.id)" @click="open('social',a)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="a.path"/></svg><span>{{a.name}}</span></button></div></div>
 </footer>
 <dialog ref="dialog" class="wash-dialog footer-contact-dialog" :aria-label="title" @cancel.prevent="close" @close="emit('open',false)"><header><h2>{{title}}</h2><button :aria-label="t.close" @click="close"><WashIcon name="close"/></button></header>
 <div v-if="kind==='operator'" class="operator-dialog-body"><WashIcon name="help"/><h3>POST {{post}}</h3><p role="status">{{callMessage}}</p><p v-if="preview">DEMO</p><strong v-if="phone" class="operator-phone">{{phone}}</strong><p v-else>{{t.phoneMissing}}</p><button v-if="uncertain||['unknown','failed','unavailable'].includes(call?.status)" class="sheet-action" :disabled="busy" @click="invoke">{{t.callRetry}}</button><button class="sheet-action" @click="close">{{t.close}}</button></div>
 <div v-else-if="kind==='service'" class="manufacturer-dialog-body"><h3>{{t.manufacturer}}</h3><dl><div v-for="id in ['marketing','programmer','electrician']" :key="id"><dt>{{t[id]}}</dt><dd><strong v-if="manufacturer[id]">{{manufacturer[id]}}</strong><span v-else>{{t.phoneMissing}}</span></dd></div></dl><div class="manufacturer-qr-grid"><section v-for="a in socialAccounts" :key="a.id"><QrcodeVue :value="url(a.id)" :size="220" level="M" render-as="svg"/><h4>{{a.name}}</h4></section></div><button class="sheet-action" @click="close">{{t.close}}</button></div>
 <div v-else class="social-dialog-body"><QrcodeVue v-if="selected&&url(selected.id)" :value="url(selected.id)" :size="360" level="M" render-as="svg" class="payment-qr"/><p>@labrixwash</p><p class="social-url">{{selected&&url(selected.id)}}</p><p>{{t.socialScan}}</p><button class="sheet-action" @click="close">{{t.close}}</button></div>
 </dialog>
</template>
<style scoped>
.footer-dev-refresh{flex:none;min-width:72px;min-height:48px;padding:6px 10px;border:1px dashed currentColor;border-radius:10px;background:transparent;font-size:16px!important;color:inherit;touch-action:manipulation}
.wash-footer .footer-operator-button{display:flex;align-items:center;gap:8px;min-height:48px;padding:6px 14px;border:1px solid var(--wash-border);border-radius:10px;background:var(--wash-panel);font-size:calc(23 * var(--u));color:var(--wash-text)}.footer-operator-button svg{width:calc(29 * var(--u));height:calc(29 * var(--u))}.footer-manufacturer{font-size:calc(18 * var(--u));color:var(--wash-muted)}.wash-footer .footer-service-button{font-size:calc(19 * var(--u));font-weight:600;min-height:48px;padding:8px 18px;background:#163c50;border:1px solid #43819e;border-radius:12px;color:#ecf8ff;cursor:pointer;white-space:nowrap;box-shadow:inset 0 1px #ffffff12;transition:background .15s,border-color .15s}.wash-footer .footer-service-button:hover{background:#20536b;border-color:#63badf}.wash-footer .footer-service-button:active{background:#0c2b3b}.wash-kiosk[data-theme="light"] .footer-service-button{background:#e0f1fb;border-color:#87b5d0;color:#123d55;box-shadow:inset 0 1px #fff}.wash-kiosk[data-theme="light"] .footer-service-button:hover{background:#cde8f7}.wash-kiosk[data-theme="light"] .footer-service-button:active{background:#b7dcee}.footer-social-links{gap:calc(14 * var(--u))}.footer-phone{font-size:calc(24 * var(--u))}.operator-dialog-body,.manufacturer-dialog-body{padding:28px;font-size:26px;line-height:1.4}.operator-dialog-body{text-align:center}.operator-dialog-body>svg{width:72px;height:72px}.operator-dialog-body>.operator-phone{font-size:36px;color:inherit}.manufacturer-dialog-body dl{margin:20px 0}.manufacturer-dialog-body dl>div{display:flex;justify-content:space-between;gap:20px;padding:18px 0;border-bottom:1px solid #8aa0b340}.manufacturer-dialog-body dd{margin:0}.manufacturer-dialog-body a{color:inherit}.manufacturer-dialog-body dd>span{font-size:20px;opacity:.7}.manufacturer-qr-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;text-align:center}.footer-contact-dialog .manufacturer-qr-grid svg{display:block;width:220px;height:220px;background:#fff;padding:12px;box-sizing:border-box;max-width:100%;margin:0 auto}.manufacturer-qr-grid h4{margin:10px 0}

.wash-footer .footer-social-links{gap:calc(8 * var(--u))}
.wash-footer .footer-social-links button{display:inline-flex;align-items:center;justify-content:center;gap:calc(7 * var(--u));min-height:48px;padding:8px 12px;border:1px solid #ffffff26;border-radius:12px;font-size:calc(18 * var(--u));font-weight:600;color:#fff;white-space:nowrap;cursor:pointer;box-shadow:inset 0 1px #ffffff18;transition:filter .15s}
.wash-footer .footer-social-links button[data-brand="telegram"]{background:#007eaf!important}
.wash-footer .footer-social-links button[data-brand="instagram"]{background:linear-gradient(125deg,#6439aa,#ad286c 50%,#be4928)!important}
.wash-footer .footer-social-links button[data-brand="youtube"]{background:#cc1717!important}
.wash-footer .footer-social-links button:hover:not(:disabled){filter:brightness(1.12)}
.wash-footer .footer-social-links button:active:not(:disabled){filter:brightness(.88)}
.wash-footer .footer-social-links button:disabled{opacity:.4;cursor:default}
.wash-footer .footer-social-links button svg{flex:none;color:inherit}
.wash-kiosk[data-theme="light"] .wash-footer .footer-social-links button{color:#fff}
.wash-footer .footer-social-links button span,.wash-footer .footer-social-links button svg{color:inherit}
</style>
