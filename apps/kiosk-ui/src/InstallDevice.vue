<script setup>
import {ref,onMounted} from 'vue'
import {api} from './api'
const props=defineProps({language:String})
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
const value=ref('wash'),status=ref(null),error=ref(''),busy=ref(false)
async function load(){status.value=await api('/api/commissioning/device');value.value=status.value.requested.type}
async function save(){busy.value=true;error.value='';try{status.value=await api('/api/commissioning/device',{method:'POST',body:JSON.stringify({type:value.value,display_name:''})})}catch(e){error.value=e.message}finally{busy.value=false}}
onMounted(()=>load().catch(e=>error.value=e.message))
</script>
<template><section class="card content"><h2>{{tr('Назначение устройства','Qurilma vazifasi','Device purpose')}}</h2><p v-if="error" class="message error">{{error}}</p><label>{{tr('Тип устройства','Qurilma turi','Device type')}}<select :aria-label="tr('Тип устройства','Qurilma turi','Device type')" v-model="value" :disabled="busy"><option value="wash">{{tr('Моечный пост','Yuvish posti','Wash station')}}</option><option value="dry_fog">{{tr('Сухой туман','Quruq tuman','Dry fog')}}</option></select></label><p>{{tr('У каждого устройства свой номер. Сухой туман может быть главным или резервным для кошелька и Telegram.','Har bir qurilmaning o‘z raqami bor. Quruq tuman hamyon va Telegram uchun asosiy yoki zaxira bo‘lishi mumkin.','Each device has its own number. Dry fog can be the primary or standby for wallet and Telegram.')}}</p><button class="quiet" :disabled="busy||!status||value===status.requested.type" @click="save">{{tr('Сохранить тип','Turni saqlash','Save type')}}</button><p v-if="status&&status.active_type!==status.requested.type" role="status">{{tr('Выбор сохранён. Примените соответствующий профиль оборудования перед запуском.','Tanlov saqlandi. Ishga tushirishdan oldin mos uskuna profilini qo‘llang.','Selection saved. Apply the matching hardware profile before launch.')}}</p></section></template>
