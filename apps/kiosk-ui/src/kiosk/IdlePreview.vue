<script setup>
import { ref } from 'vue'
import IdleScreen from './IdleScreen.vue'
const language = ref('uz')
const showing = ref(true)
</script>
<template>
  <IdleScreen v-if="showing" v-model:language="language" @wake="showing = false" />
  <main v-else class="preview-return">
    <p>Предпросмотр · LABRIX WASH</p>
    <h1>Заставка закрыта</h1>
    <p>Рабочий экран мойки подключается следующим этапом.</p>
    <button @click="showing = true">Вернуться к заставке</button>
    <a href="/login">Вход в управление</a>
  </main>
</template>
<style scoped>
.preview-return { min-height:100dvh; background:#020c19; color:#fff; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:24px; padding:40px; text-align:center; }.preview-return h1 { font-size:48px; }.preview-return p { font-size:24px; }.preview-return button { background:#08263d; border:1px solid #00c8ee; padding:24px 40px; border-radius:16px; color:#fff; font-size:24px; }.preview-return a { color:#00c8ee; font-size:22px; }
</style>
