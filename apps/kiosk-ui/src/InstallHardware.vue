<script setup>
import {ref,computed,onMounted,onUnmounted} from 'vue'
import {api} from './api'
import {requestErrorText} from './request-error'
const props=defineProps({language:String,disabled:Boolean})
const emit=defineEmits(['busy','ready'])
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
const pending=ref(false),result=ref(''),error=ref('')

const messages={
failed:()=>tr('Не удалось применить оборудование. Проверьте подключение и питание Modbus. Для сухого тумана сначала укажите тип поста на главном. После проверки повторите попытку.','Uskunani qo‘llab bo‘lmadi. Modbus ulanishi va quvvatini tekshiring. Quruq tuman uchun avval asosiy postda turini belgilang. Tekshirgach qayta urinib ko‘ring.','Could not apply hardware. Check Modbus wiring and power. For dry fog, configure the station type on the primary first, then retry.'),
success:()=>tr('Профиль применён, связь Modbus проверена.','Profil qo‘llandi, Modbus aloqasi tekshirildi.','Profile applied; Modbus connection verified.'),
missing:()=>tr('Операция не найдена. Обновите страницу и повторите применение оборудования.','Amal topilmadi. Sahifani yangilang va uskunani qayta qo‘llang.','Operation not found. Refresh the page and retry applying hardware.'),
reconnecting:()=>tr('Ожидаем восстановления связи с постом…','Post bilan aloqa tiklanishini kutyapmiz…','Waiting for the station to reconnect…')
}
const resultText=computed(()=>messages[result.value]?.()||result.value)
const errorText=computed(()=>messages[error.value]?.()||requestErrorText(error.value,props.language))
const storageKey='labrix-install-hardware-job'
let stopped=false,timer=null,wake=null
function setBusy(value){pending.value=value;emit('busy',value)}
function delay(){return new Promise(resolve=>{wake=resolve;timer=setTimeout(resolve,2000)})}
async function watchJob(id){
  setBusy(true)
  try{
    while(!stopped){
      try{
        const job=await api('/api/system/actions/'+id)
        if(job.status==='completed'||job.status==='failed'){
          sessionStorage.removeItem(storageKey)
          result.value='';error.value=''
          if(job.status==='failed')error.value='failed'
          else result.value='success'
          setBusy(false);emit('ready');return
        }
      }catch(e){
        if(e.status===404){
          sessionStorage.removeItem(storageKey)
          error.value='missing'
          setBusy(false);return
        }
        // The backend is expected to disappear while its profile is applied.
        result.value='reconnecting'
      }
      await delay()
    }
  }finally{if(!stopped)setBusy(false)}
}
function newRequestId(){
  if(crypto.randomUUID)return crypto.randomUUID()
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128
  return [...bytes].map((v,i)=>([4,6,8,10].includes(i)?'-':'')+v.toString(16).padStart(2,'0')).join('')
}
async function apply(){
  if(pending.value||props.disabled)return
  error.value='';result.value='';setBusy(true)
  const id=newRequestId()
  // Store before POST: a lost response must not result in a second operation.
  sessionStorage.setItem(storageKey,id)
  try{
    await api('/api/commissioning/hardware',{method:'POST',body:JSON.stringify({request_id:id})})
  }catch(e){
    if(e.status>=400&&e.status<500){sessionStorage.removeItem(storageKey);error.value=e;setBusy(false);return}
    error.value=e
    // Keep the receipt: request acceptance may have preceded a network failure.
  }
  await watchJob(id)
}
onMounted(()=>{const id=sessionStorage.getItem(storageKey);if(id)watchJob(id)})
onUnmounted(()=>{stopped=true;clearTimeout(timer);wake?.()})
</script>
<template><section class="card content">
  <h2>{{tr('Подключение оборудования','Uskunani ulash','Hardware connection')}}</h2>
  <p>{{tr('Подключите оборудование согласно выбранной модели платы и включите питание. Применение профиля перезапустит службы поста; выходы остаются выключенными.','Tanlangan plata modeliga mos uskunani ulang va quvvatini yoqing. Profil qo‘llanganda post xizmatlari qayta ishga tushadi; chiqishlar o‘chiq qoladi.','Connect the hardware for the selected board model and turn on its power. Applying the profile restarts station services; outputs remain OFF.')}}</p>
  <p v-if="pending" role="status">{{tr('Применяем оборудование. Дождитесь завершения…','Uskuna qo‘llanmoqda. Tugashini kuting…','Applying hardware. Please wait…')}}</p>
  <p v-if="result" role="status">{{resultText}}</p><p v-if="error" class="message error" role="alert">{{errorText}}</p>
  <button class="primary" :disabled="disabled||pending" @click="apply">{{tr('Применить оборудование','Uskunani qo‘llash','Apply hardware')}}</button>
</section></template>
