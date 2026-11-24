<script setup>
import {ref,onBeforeUnmount} from 'vue'
import {setupHelp} from './setup-help.js'
const props=defineProps({kind:{type:String,required:true},language:{type:String,default:'ru'}})
const dialog=ref(null)
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
onBeforeUnmount(()=>dialog.value?.close())
</script>
<template>
<button type="button" class="quiet setup-help-button" aria-haspopup="dialog" @click="dialog.showModal()">ⓘ {{tr('Как подключить','Qanday ulash kerak','How to connect')}}</button>
<Teleport to="body"><dialog ref="dialog" class="setup-help-dialog" :aria-label="tr('Инструкция по подключению','Ulash bo‘yicha yo‘riqnoma','Connection instructions')" @click="e=>{if(e.target===dialog)dialog.close()}">
<header><h2>{{kind==='telegram'?'Telegram':tr('Общий кошелёк','Umumiy hamyon','Shared wallet')}}</h2><button type="button" class="quiet" autofocus @click="dialog.close()">{{tr('Закрыть','Yopish','Close')}} ✕</button></header>
<ol><li v-for="(step,i) in setupHelp[kind][language]||setupHelp[kind].ru" :key="i">{{step}}</li></ol>
</dialog></Teleport>
</template>
<style scoped>
.setup-help-button{margin:12px 0}.setup-help-dialog{color:var(--text,#182433);background:var(--surface,#fff);border:1px solid var(--border,#ccd5df);border-radius:14px;width:min(680px,calc(100vw - 36px));max-height:85dvh;padding:24px;box-sizing:border-box;overflow:auto}.setup-help-dialog::backdrop{background:#0009}.setup-help-dialog header{display:flex;align-items:center;justify-content:space-between;gap:16px}.setup-help-dialog h2{margin:0;font-size:24px}.setup-help-dialog li{line-height:1.6;padding-left:8px;margin:18px 0}.setup-help-dialog ol{padding-left:24px}
</style>
