<script setup>
import {ref,onMounted} from 'vue'
import {api} from './api'
const props=defineProps({token:String,language:String,mode:String})
const emit=defineEmits(['dirty'])
const tr=(ru,uz,en)=>props.language==='uz'?uz:props.language==='en'?en:ru
const data=ref(null),busy=ref(false),error=ref(''),notice=ref(''),draft=ref(null),chosen=ref(null),confirmation=ref(''),dirty=ref(false),after=ref(''),history=ref([])
const request=(url,options={})=>api(url,{token:props.token,...options})
const changed=()=>{dirty.value=true;emit('dirty',true)}
const clean=()=>{dirty.value=false;emit('dirty',false)}
const sum=n=>Number(n||0).toLocaleString(props.language==='ru'?'ru-RU':'en-US')
const label=s=>({active:tr('Активна','Faol','Active'),blocked:tr('Заблокирована','Bloklangan','Blocked'),lost:tr('Утеряна','Yo‘qolgan','Lost'),expired:tr('Истекла','Muddati tugagan','Expired')})[s]||s
async function run(fn){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false}}
async function load(){data.value=await request((props.mode==='local'?'/api/owner/wallet/local-import?':'/api/owner/wallet/customers?')+new URLSearchParams({after:after.value,limit:30}))}
function edit(c){draft.value={uid:c?.uid||'',display_name:c?.display_name||'',enabled:c?.enabled??true,status:c?.status||'active',expected_revision:c?.revision||0};clean()}
async function read(){const r=await request('/api/owner/rfid/latest');if(!r.online||!r.latest||Date.now()-new Date(r.latest.seen_at)>15000)throw Error(tr('Приложите карту и повторите чтение','Kartani qo‘ying va qayta o‘qing','Present a card and read again'));draft.value.uid=r.latest.uid;changed()}
async function save(){await request('/api/owner/wallet/customers',{method:'POST',body:JSON.stringify(draft.value)});draft.value=null;clean();await load();notice.value=tr('Карта сохранена. Денежный остаток не изменён.','Karta saqlandi. Pul qoldig‘i o‘zgarmadi.','Card saved. Monetary balance is unchanged.')}
async function migrate(){const c=chosen.value,amount=c.import_sum||c.balance_sum;await request('/api/owner/wallet/local-import',{method:'POST',body:JSON.stringify({uid:c.uid,amount_sum:Number(amount),confirmation:confirmation.value})});chosen.value=null;confirmation.value='';clean();await load();notice.value=tr('Остаток перенесён в общий кошелёк.','Qoldiq umumiy hamyonga ko‘chirildi.','Balance transferred to the shared wallet.')}
async function next(){history.value.push(after.value);after.value=data.value.next_after;await load()}
async function previous(){after.value=history.value.pop()||'';await load()}
onMounted(()=>run(load))
</script>
<template>
<section class="card content customer-cards">
<h2>{{mode==='local'?tr('Локальные остатки этого поста','Ushbu postning mahalliy qoldiqlari','Local balances on this station'):tr('Денежные карты','Pul kartalari','Customer money cards')}}</h2>
<p v-if="mode==='local'" class="muted">{{tr('Перенос из локальной базы SAMMOY 2. Пост должен быть без активного сеанса. Новые деньги не создаются; локальная карта блокируется, остаток обнуляется только после подтверждения общего кошелька.','SAMMOY 2 mahalliy bazasidan ko‘chirish. Postda faol seans bo‘lmasligi kerak. Yangi pul yaratilmaydi; mahalliy karta bloklanadi, qoldiq umumiy hamyon tasdiqlagandan keyin nolga tushiriladi.','Transfer from the local SAMMOY 2 database. This station must have no active session. No new revenue is created; the local card is frozen and cleared only after wallet confirmation.')}}</p>
<p v-else class="muted">{{tr('Остаток на карте и деньги активного поста показаны отдельно. Имя и статус можно менять на главном посту; остаток вручную не редактируется.','Karta qoldig‘i va faol postdagi pul alohida ko‘rsatiladi. Ism va holatni asosiy postda o‘zgartirish mumkin; qoldiq qo‘lda tahrirlanmaydi.','Card balance and money on the active station are shown separately. Edit names and status on the primary station; balances cannot be edited manually.')}}</p>
<p v-if="error" role="alert" class="message error">{{error}}</p><p v-if="notice" role="status" class="message success">{{notice}}</p>
<div class="actions"><button class="quiet" :disabled="busy||dirty" @click="run(load)">{{tr('Обновить','Yangilash','Refresh')}}</button><button v-if="mode!=='local'" class="primary" :disabled="busy||dirty||!data?.can_edit" @click="edit()">{{tr('Добавить карту','Karta qo‘shish','Add card')}}</button></div>
<form v-if="draft" class="fields" @submit.prevent="run(save)" @input="changed" @change="changed">
<label>UID<input v-model="draft.uid" pattern="[0-9A-Fa-f]{4,64}" maxlength="64" required :readonly="draft.expected_revision>0"/></label>
<div class="actions"><button class="quiet" type="button" :disabled="busy||draft.expected_revision>0" @click="run(read)">PN532</button></div>
<label>{{tr('Имя владельца','Karta egasi','Cardholder')}}<input v-model="draft.display_name" maxlength="120"/></label>
<label>{{tr('Статус','Holat','Status')}}<select v-model="draft.status" :aria-label="tr('Статус','Holat','Status')"><option v-for="s in ['active','blocked','lost','expired']" :value="s">{{label(s)}}</option></select></label>
<label class="check"><input type="checkbox" v-model="draft.enabled"/>{{tr('Включена','Yoqilgan','Enabled')}}</label>
<div class="actions"><button class="primary" :disabled="busy||!dirty">{{tr('Сохранить','Saqlash','Save')}}</button><button class="quiet" type="button" @click="draft=null;clean()">{{tr('Отмена','Bekor qilish','Cancel')}}</button></div>
</form>
<div class="table-wrap" v-if="data"><table><thead><tr><th>UID</th><th>{{tr('Владелец','Egasi','Cardholder')}}</th><th>{{tr('Остаток, сум','Qoldiq, so‘m','Balance, sum')}}</th><th>{{mode==='local'?tr('Перенос','Ko‘chirish','Transfer'):tr('На посту, сум','Postda, so‘m','At station, sum')}}</th><th>{{tr('Статус','Holat','Status')}}</th><th></th></tr></thead><tbody><tr v-for="c in data.cards" :key="c.uid"><th>{{c.uid}}</th><td>{{c.display_name||'—'}}</td><td>{{sum(c.balance_sum)}}<small v-if="c.bonus_sum" style="display:block">{{tr("Включая бонус","Shu jumladan bonus","Including bonus")}}: {{sum(c.bonus_sum)}}</small></td><td>{{mode==='local'?(c.import_status==='pending'?tr('Ожидает подтверждения','Tasdiq kutilmoqda','Awaiting confirmation'):c.import_status==='done'?tr('Перенесён','Ko‘chirildi','Transferred'):'—'):sum(c.assigned_sum)}}<span v-if="c.assigned_post"> · #{{c.assigned_post}}</span></td><td>{{label(c.status)}}{{c.enabled?'':' · OFF'}}</td><td><button class="quiet" :disabled="busy||dirty||(mode==='local'?!data.enabled:c.pending||!data.can_edit)" @click="mode==='local'?(chosen=c,confirmation='',clean()):edit(c)">{{mode==='local'?(c.import_status==='pending'?tr('Повторить','Qayta urinish','Retry'):tr('Перенести','Ko‘chirish','Transfer')):tr('Изменить','Tahrirlash','Edit')}}</button></td></tr></tbody></table></div>
<p v-if="data&&!data.cards.length" class="muted">{{tr('Записей нет','Yozuvlar yo‘q','No records')}}</p>
<p v-if="data?.truncated" class="muted">{{tr('Показаны первые 100 карт. После переноса обновите список.','Birinchi 100 karta ko‘rsatilgan. Ko‘chirishdan keyin ro‘yxatni yangilang.','Showing the first 100 cards. Refresh after transferring.')}}</p>
<form v-if="chosen" class="fields import-confirm" @submit.prevent="run(migrate)"><p>{{chosen.uid}} · {{sum(chosen.import_sum||chosen.balance_sum)}} so‘m</p><label>{{tr('Введите для подтверждения','Tasdiqlash uchun kiriting','Type to confirm')}}: IMPORT {{chosen.uid}} {{chosen.import_sum||chosen.balance_sum}}<input v-model="confirmation" autocomplete="off" @input="changed"/></label><div class="actions"><button class="primary" :disabled="busy||confirmation!==`IMPORT ${chosen.uid} ${chosen.import_sum||chosen.balance_sum}`">{{tr('Подтвердить перенос','Ko‘chirishni tasdiqlash','Confirm transfer')}}</button><button class="quiet" type="button" @click="chosen=null;clean()">{{tr('Закрыть','Yopish','Close')}}</button></div></form>
<div class="actions"><button class="quiet" :disabled="busy||dirty||!history.length" @click="run(previous)">←</button><button class="quiet" :disabled="busy||dirty||!data?.next_after" @click="run(next)">→</button></div>
</section>
</template>
<style scoped>
.customer-cards h2{margin:0 0 16px}.customer-cards>p{line-height:1.6}.customer-cards .fields{margin:24px 0;padding:0}.customer-cards .actions{margin:20px 0}.import-confirm{border-top:1px solid var(--border);padding-top:24px!important}.customer-cards input[readonly]{opacity:.7}
</style>
