<script setup>
import { computed } from 'vue'
const props=defineProps({modelValue:String,label:String})
const emit=defineEmits(['update:modelValue'])
const parts=computed(()=>(props.modelValue||'08:00').split(':'))
const pad=n=>String(n).padStart(2,'0')
function set(part,value){const next=[...parts.value];next[part]=value;emit('update:modelValue',next.join(':'))}
</script>
<template><div class="time-select" role="group" :aria-label="label"><select :aria-label="label+' HH'" :value="parts[0]" @change="set(0,$event.target.value)"><option v-for="n in 24" :key="n" :value="pad(n-1)">{{ pad(n-1) }}</option></select><span aria-hidden="true">:</span><select :aria-label="label+' mm'" :value="parts[1]" @change="set(1,$event.target.value)"><option v-for="n in 60" :key="n" :value="pad(n-1)">{{ pad(n-1) }}</option></select></div></template>
<style scoped>.time-select{display:flex;align-items:center;gap:12px}.time-select select{flex:1;min-height:56px}.time-select span{font-size:24px}</style>
