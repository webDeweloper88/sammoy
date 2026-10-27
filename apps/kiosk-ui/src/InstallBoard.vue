<script setup>
import {ref,onMounted,onUnmounted} from 'vue'
import {api} from './api'
const props=defineProps({language:String,disabled:Boolean})
const emit=defineEmits(['busy','ready'])
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
const data=ref(null),selected=ref(''),pending=ref(false),error=ref('')
let stopped=false
async function load(){
  try{data.value=await api('/api/commissioning/board');selected.value=data.value.selection?.board_id||data.value.detection.suggested_board||'';error.value='';emit('ready',Boolean(data.value.selection?.confirmed))}
  catch(e){error.value=e.message}
}
async function confirm(){
  if(pending.value||!selected.value)return
  pending.value=true;emit('busy',true);error.value=''
  const id=crypto.randomUUID?.()||'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const n=crypto.getRandomValues(new Uint8Array(1))[0]&15;return (c==='x'?n:(n&3)|8).toString(16)})
  // Receipt survives reload; never create a second job for a lost response.
  sessionStorage.setItem('labrix-board-job',id)
  try{await api('/api/commissioning/board',{method:'POST',body:JSON.stringify({board_id:selected.value,request_id:id})})}
  catch(e){if(e.status>=400&&e.status<500){sessionStorage.removeItem('labrix-board-job');error.value=e.message;pending.value=false;emit('busy',false);return}}
  await watchJob(id)
}
async function watchJob(id){
  pending.value=true;emit('busy',true)
  try{
    while(!stopped){
      try{
        const job=await api('/api/system/actions/'+id)
        if(job.status==='completed'||job.status==='failed'){
          sessionStorage.removeItem('labrix-board-job');await load()
          if(job.status==='failed')error.value=tr('Выбор не подтверждён. Проверьте модель платы и состояние поста.','Tanlov tasdiqlanmadi. Plata modelini va post holatini tekshiring.','Selection failed. Check the board model and station state.')
          return
        }
      }catch(e){if(e.status===404){sessionStorage.removeItem('labrix-board-job');error.value=e.message;return}}
      await new Promise(resolve=>setTimeout(resolve,1500))
    }
  }finally{pending.value=false;emit('busy',false)}
}
onMounted(async()=>{await load();const id=sessionStorage.getItem('labrix-board-job');if(id)await watchJob(id)})
onUnmounted(()=>{stopped=true})
</script>
<template><section class="card content">
<h2>{{tr('Модель платы','Plata modeli','Controller board')}}</h2>
<p>{{tr('Проверьте модель по маркировке платы. Выбор сохраняется и не меняется при обновлении ПО.','Plata ustidagi modelni tekshiring. Tanlov saqlanadi va dastur yangilanganda o‘zgarmaydi.','Check the model printed on your board. Updates preserve your confirmed selection.')}}</p>
<template v-if="data">
<p v-if="data.selection" class="message success">{{tr('Модель подтверждена','Model tasdiqlangan','Confirmed model')}}: {{data.profiles.find(p=>p.id===data.selection.board_id)?.name}}</p>
<template v-else>
<p>{{data.detection.suggested_board?tr('Предложена модель — проверьте и подтвердите.','Tavsiya etilgan modelni tekshiring va tasdiqlang.','Suggested model — verify and confirm.'):tr('Плата не определена однозначно. Выберите модель вручную.','Plata aniq aniqlanmadi. Modelni qo‘lda tanlang.','Board not identified. Select the model manually.')}}</p>
<label>{{tr('Модель','Model','Model')}}<select v-model="selected" :disabled="disabled||pending"><option value="">{{tr('Выберите плату','Platani tanlang','Select board')}}</option><option v-for="p in data.profiles" :key="p.id" :value="p.id">{{p.name}}</option></select></label>
<button class="primary" :disabled="disabled||pending||!selected" @click="confirm">{{pending?tr('Сохраняем…','Saqlanmoqda…','Saving…'):tr('Подтвердить модель','Modelni tasdiqlash','Confirm board')}}</button>
</template></template>
<p v-if="error" class="message error" role="alert">{{error}}</p><button v-if="error&&!pending" class="quiet" @click="load">{{tr('Повторить проверку','Qayta tekshirish','Retry')}}</button>
</section></template>
