<script setup>
import {ref,onMounted,onUnmounted} from 'vue'
import {api} from './api.js'
const props=defineProps({token:String,language:String})
const emit=defineEmits(['open'])
const notice=ref(null);let timer,stopped=false
async function check(){try{notice.value=await api('/api/owner/updates/notice',{token:props.token,signal:AbortSignal.timeout(15000)})}catch{notice.value=null}if(!stopped)timer=setTimeout(check,15*60*1000)}
onMounted(check);onUnmounted(()=>{stopped=true;clearTimeout(timer)})
</script>
<template><p v-if="notice?.available" class="message" role="status">{{language==='uz'?'Dastur yangilanishi mavjud':language==='en'?'Software update available':'Доступно обновление ПО'}}: {{notice.version}} <button class="quiet" @click="emit('open')">{{language==='uz'?'Ko‘rish':language==='en'?'View':'Посмотреть'}}</button></p></template>
