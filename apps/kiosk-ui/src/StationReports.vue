<script setup>
import SiteOwner from './SiteOwner.vue'
defineProps({token:String,language:String})
const emit=defineEmits(['dirty'])
</script>
<template><SiteOwner :token="token" :language="language" initial-view="reports" @dirty="emit('dirty',$event)"/></template>
