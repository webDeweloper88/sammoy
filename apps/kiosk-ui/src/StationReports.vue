<script setup>
import { ref,onMounted } from 'vue'
import { api } from './api'
const props=defineProps({token:String,language:String})
const tr=(ru,uz,en)=>({ru,uz,en}[props.language]||ru)
const period=ref('daily'),date=ref(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tashkent',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()))
const report=ref(null),error=ref(''),busy=ref(false)
const n=v=>Number(v||0).toLocaleString('ru-RU')
async function load(){busy.value=true;error.value='';try{report.value=await api('/api/owner/reports/stations?'+new URLSearchParams({period:period.value,value:date.value}),{token:props.token})}catch(e){error.value=e.message}finally{busy.value=false}}
onMounted(load)
</script>
<template><section>
<form class="card content" @submit.prevent="load"><div class="fields"><label>{{ tr('Период','Davr','Period') }}<select v-model="period"><option value="daily">{{ tr('День','Kun','Day') }}</option><option value="weekly">{{ tr('Неделя','Hafta','Week') }}</option><option value="monthly">{{ tr('Месяц','Oy','Month') }}</option></select></label><label>{{ tr('Дата в выбранном периоде','Tanlangan davrdagi sana','Date within period') }}<input type="date" v-model="date" required /></label><button class="primary" :disabled="busy">{{ busy?tr('Загрузка…','Yuklanmoqda…','Loading…'):tr('Показать','Ko‘rsatish','Show') }}</button></div></form>
<div v-if="error" class="message error" role="alert">{{ error }}</div>
<template v-if="report"><div v-if="report.status!=='ok'" class="message error">{{ tr('Не все посты доступны. Итог включает только ответившие посты.','Barcha postlar mavjud emas. Jami faqat javob bergan postlarni o‘z ichiga oladi.','Some stations are unavailable. Totals include responding stations only.') }}</div><div v-if="report.summary" class="metrics"><div class="card metric"><p>{{ tr('Наличные, сум','Naqd, so‘m','Cash, sum') }}</p><strong>{{ n(report.summary.cash_amount) }}</strong></div><div class="card metric"><p>Click, {{ tr('сум','so‘m','sum') }}</p><strong>{{ n(report.summary.click_amount) }}</strong></div><div class="card metric"><p>{{ tr('Всего, сум','Jami, so‘m','Total, sum') }}</p><strong>{{ n(report.summary.total_amount) }}</strong></div><div class="card metric"><p>{{ tr('Посты онлайн','Onlayn postlar','Stations online') }}</p><strong>{{ report.summary.online_posts }} / {{ report.posts.length }}</strong></div></div><section class="card"><div class="table-wrap"><table><thead><tr><th>{{ tr('Пост','Post','Station') }}</th><th>{{ tr('Статус','Holat','Status') }}</th><th>{{ tr('Наличные','Naqd','Cash') }}</th><th>Click</th><th>{{ tr('Сеансы','Seanslar','Sessions') }}</th></tr></thead><tbody><tr v-for="p in report.posts" :key="p.post_id"><th>{{ p.name }}</th><td>{{ p.status==='online'?'Online':'Offline' }}</td><td>{{ p.report?n(p.report.cash_amount):'—' }}</td><td>{{ p.report?n(p.report.click_amount):'—' }}</td><td>{{ p.report?n(p.report.total_sessions):'—' }}</td></tr></tbody></table></div></section></template>
</section></template>
