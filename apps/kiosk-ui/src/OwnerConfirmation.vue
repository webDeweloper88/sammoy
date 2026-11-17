<script setup>
import {ref,onMounted,onUnmounted} from 'vue'
const password=ref(''),pending=ref(null)
const props=defineProps({language:String})
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
function request(e){if(pending.value){e.detail.resolve(null);return}pending.value=e.detail;password.value=''}
function finish(value){pending.value?.resolve(value);pending.value=null;password.value=''}
onMounted(()=>window.addEventListener('sammoy-owner-confirmation',request))
onUnmounted(()=>{window.removeEventListener('sammoy-owner-confirmation',request);finish(null)})
</script>
<template><div v-if="pending" class="confirm-backdrop"><form class="card confirm-dialog" role="dialog" aria-modal="true" @submit.prevent="finish(password)"><h2>{{tr('Подтвердите действие паролем Owner','Amalni Owner paroli bilan tasdiqlang','Confirm action with Owner password')}}</h2><label>{{tr('Пароль Owner','Owner paroli','Owner password')}}<input v-model="password" type="password" autocomplete="current-password" maxlength="200" required autofocus /></label><button class="primary">{{tr('Подтвердить','Tasdiqlash','Confirm')}}</button><button type="button" @click="finish(null)">{{tr('Отмена','Bekor qilish','Cancel')}}</button></form></div></template>
