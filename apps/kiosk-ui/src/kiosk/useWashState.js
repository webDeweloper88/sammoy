import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api.js'
export function useWashState(){
 const state=ref(null),parameters=ref(null),config=ref(null),paymentOptions=ref(null),station=ref(null),receivedAt=ref(0),now=ref(Date.now()),busy=ref(false),error=ref(false)
 let stopped=false,timer,clock,controller,configAt=0,version=0
 const fresh=computed(()=>receivedAt.value>0 && now.value-receivedAt.value<4000)
 const ready=computed(()=>fresh.value && state.value?.lastIoOk===true && Number.isFinite(state.value?.runtimeAgeSeconds) && state.value.runtimeAgeSeconds<5 && !state.value?.lastError && !state.value?.licenseLocked && !state.value?.walletTransferPending && !!config.value)
 function accept(data){if(stopped)return;state.value=data.state;parameters.value=data.parameters;receivedAt.value=Date.now();now.value=Date.now()}
 async function poll(){
  const before=version
  controller=new AbortController()
  const timeout=setTimeout(()=>controller?.abort(),3000)
  try {
   const data=await api('/api/wash/state',{signal:controller.signal})
   if(version===before&&!busy.value)accept(data)
  }catch{if(!stopped)receivedAt.value=0}finally{clearTimeout(timeout)}
  if(!stopped&&Date.now()-configAt>1000){
   configAt=Date.now()
   const results=await Promise.allSettled([api('/api/kiosk/settings',{signal:AbortSignal.timeout(3000)}),api('/api/kiosk/payment-options',{signal:AbortSignal.timeout(3000)})])
   if(!stopped){if(results[0].status==='fulfilled')station.value=results[0].value.station;config.value=results[0].status==='fulfilled'?results[0].value.config:null;paymentOptions.value=results[1].status==='fulfilled'?results[1].value:null}
  }
  if(!stopped)timer=setTimeout(poll,250)
 }
 async function select(mode){
  // Pause remains callable during an I/O failure; never queue or retry a start.
  if(busy.value || (mode!=='pause'&&!ready.value))return false
  busy.value=true;error.value=false;version++
  try{const data=await api('/api/wash/mode',{method:'POST',body:JSON.stringify({mode}),signal:AbortSignal.timeout(4000)});accept(data);return true}
  catch{error.value=true;receivedAt.value=0;return false}
  finally{version++;busy.value=false}
 }
 onMounted(()=>{poll();clock=setInterval(()=>now.value=Date.now(),250)})
 onUnmounted(()=>{stopped=true;clearTimeout(timer);clearInterval(clock);controller?.abort()})
 return {state,parameters,config,paymentOptions,station,receivedAt,now,fresh,ready,busy,error,select}
}
