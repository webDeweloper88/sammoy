<script setup>
import { computed,ref } from 'vue'
const props=defineProps({modelValue:String,context:Object,post:Number,language:String})
const emit=defineEmits(['update:modelValue'])
const full=ref(false)
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
const base=computed(()=>'http://'+props.context.stem)
const short=computed(()=>!full.value&&props.context.stem&&(!props.modelValue||new RegExp('^http://'+props.context.stem.replaceAll('.','\\.')+'\\d{1,3}/?$').test(props.modelValue)))
const suffix=computed(()=>props.modelValue?.startsWith(base.value)?props.modelValue.slice(base.value.length).replace(/\/$/,''):'')
function change(event){const v=event.target.value.replace(/\D/g,'').slice(0,3);event.target.value=v;emit('update:modelValue',v?base.value+v:'')}
</script>
<template><div class="peer-address"><label v-if="short">{{tr('Адрес поста','Post manzili','Station address')}} {{post}}<span class="address-parts"><span>{{base}}</span><input :value="suffix" @input="change" type="text" inputmode="numeric" data-keyboard="integer" maxlength="3" :aria-label="tr('Последнее число IP поста','Post IP manzilining oxirgi soni','Last IP number for station')+' '+post" :placeholder="tr('число','son','number')" required /></span></label><label v-else>{{tr('Адрес поста','Post manzili','Station address')}} {{post}}<input :value="modelValue" @input="emit('update:modelValue',$event.target.value)" type="text" inputmode="url" placeholder="http://192.168.1.10" required /></label><button type="button" class="address-toggle" @click="full=!full">{{short?tr('Ввести полный адрес','To‘liq manzil kiritish','Enter full address'):tr('Короткий ввод','Qisqa kiritish','Short input')}}</button></div></template>
<style scoped>.peer-address{min-width:0}.address-parts{display:flex;align-items:center;border:1px solid var(--border);background:var(--input);border-radius:4px;overflow:hidden}.address-parts>span{padding:12px;white-space:nowrap;font-size:20px;color:var(--muted)}.address-parts>input{border:0!important;min-width:80px;width:100%;font-size:22px}.address-toggle{background:transparent;color:var(--accent);border:0;text-decoration:underline;text-underline-offset:4px;font-size:15px;min-height:44px;padding:8px 0;text-align:left}@media(max-width:600px){.address-parts>span{font-size:17px;padding:10px}}</style>
