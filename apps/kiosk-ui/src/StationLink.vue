<script setup>
import {computed} from 'vue'
import QrcodeVue from 'qrcode.vue'
const props=defineProps({href:String,language:String})
const localScreen=['localhost','127.0.0.1','[::1]'].includes(location.hostname)
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
const safeUrl=computed(()=>{try{const u=new URL(props.href);return ['http:','https:'].includes(u.protocol)?u.href:null}catch{return null}})
</script>
<template><span v-if="safeUrl" class="station-link"><template v-if="localScreen"><span class="station-link-hint">{{tr('Откройте на телефоне или компьютере в сети мойки:','Yuvish tarmog‘idagi telefon yoki kompyuterda oching:','Open on a phone or computer on the site network:')}}</span><code>{{safeUrl}}</code><QrcodeVue :value="safeUrl" :size="192" :margin="4" level="M" render-as="svg" :aria-label="tr('QR главного поста','Asosiy post QR kodi','Primary station QR')"/></template><a v-else :href="safeUrl" target="_blank" rel="noopener noreferrer"><slot/></a></span></template>
<style scoped>.station-link-hint{display:block;margin-top:12px}.station-link code{display:block;overflow-wrap:anywhere;margin:12px 0;font-size:inherit}.station-link svg{display:block;background:#fff;width:192px;height:192px;max-width:100%;margin:14px 0}</style>
