import {createApp,h,reactive,ref} from 'vue'
import PaymentSheet from '../src/kiosk/PaymentSheet.vue'
import AdminDetails from '../src/AdminDetails.vue'
import {washTexts} from '../src/kiosk/wash-texts.js'
const kind=new URLSearchParams(location.search).get('kind')
const state=reactive({creditSum:5000,internetOnline:true,billInputReady:true,nfcReady:true,lastRfidStatus:'online',billPulses:0})
const open=ref(false)
window.fixtureState=value=>Object.assign(state,value)
window.openPayment=()=>{open.value=true}
createApp({render:()=>kind==='admin'?h(AdminDetails,{section:'license',token:'fixture-admin',language:'ru',snapshot:{state},idle:true}):h(PaymentSheet,{open:open.value,t:washTexts.ru,ready:true,state,config:{payment:{minAmount:1000,maxAmount:100000,quickAmounts:[5000,10000]}},options:{click:{enabled:true,minAmount:1000,maxAmount:100000}},onClose:()=>{open.value=false}})}).mount('#app')
