<script setup>
import {ref,onMounted,onUnmounted} from 'vue'
import {api} from './api'
import TouchKeyboard from './TouchKeyboard.vue'
const pin=ref(''),error=ref(''),busy=ref(false)
const lang=localStorage.getItem('sammoy-ui-language')||'ru'
const tr=(ru,uz,en)=>({ru,uz,en}[lang]||ru)
let timer
onMounted(()=>{sessionStorage.removeItem('sammoy-owner-token');timer=setTimeout(()=>location.replace('/wash'),45000)})
onUnmounted(()=>clearTimeout(timer))
function back(){location.replace('/wash')}
async function enter(){
 if(busy.value)return
 busy.value=true;error.value=''
 try{
  const result=await api('/api/auth/service-pin',{method:'POST',body:JSON.stringify({challenge:sessionStorage.getItem('sammoy-service-challenge')||'',pin:pin.value})})
  sessionStorage.removeItem('sammoy-service-challenge');sessionStorage.setItem('sammoy-owner-token',result.access_token);sessionStorage.setItem('sammoy-service-session','1');location.replace('/owner/site')
 }catch(e){error.value=e.message;pin.value=''}finally{busy.value=false}
}
</script>
<template><main class="shell"><form class="card login" @submit.prevent="enter"><h1>{{tr('Вход Owner по карте','Owner karta orqali kirish','Owner card sign-in')}}</h1><label>PIN (4–12)<input v-model="pin" type="password" inputmode="numeric" data-keyboard="pin" pattern="[0-9]{4,12}" minlength="4" maxlength="12" autocomplete="off" autofocus required /></label><p role="alert">{{error}}</p><button class="primary" :disabled="busy">{{tr('Войти','Kirish','Sign in')}}</button><button type="button" @click="back">{{tr('На экран мойки','Yuvish ekraniga','Return to wash')}}</button></form><TouchKeyboard :language="lang"/></main></template>
