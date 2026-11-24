<script setup>
import TelegramConnection from './TelegramConnection.vue'
defineProps({language:String})
const emit=defineEmits(['busy'])
</script>
<template><TelegramConnection :language="language" @busy="emit('busy',$event)"/></template>
