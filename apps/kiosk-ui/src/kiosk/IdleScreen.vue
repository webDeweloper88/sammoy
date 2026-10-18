<script setup>
import { computed, ref, watch, onUnmounted } from 'vue'
import {brandTitle,brandSubtitle} from './presentation.js'
import { idleTexts, languageNames } from './idle-texts.js'
const props = defineProps({ config:Object, language: { type: String, default: 'uz' }, logo: { type: String, default: '/branding/labrixwash-logo.png' }, hero: { type: String, default: '/branding/labrixwash_idle_portrait.webp' } })
const emit = defineEmits(['wake', 'update:language'])
const heroSource=computed(()=>props.config?.layout?.backgroundImageUrl||props.hero)
const text = computed(() => idleTexts[props.language] || idleTexts.uz)
const heroMissing = ref(false)
const portraitHero = ref(false)
watch(heroSource,()=>{heroMissing.value=false;portraitHero.value=false})
function heroLoaded(event) {
  const image = event.target
  portraitHero.value = image.naturalHeight / image.naturalWidth >= 1.5
}
let removeGuard
let guardTimer
// Consume the release/click belonging to the wake gesture before the next screen sees it.
function wake(event) {
  if (event.type === 'pointerdown' && !event.isPrimary) return
  event.preventDefault()
  event.stopPropagation()
  if (event.type === 'pointerdown') {
    removeGuard?.()
    const block = e => { e.preventDefault(); e.stopImmediatePropagation(); if (e.type === 'click' || e.type === 'pointercancel') removeGuard() }
    removeGuard = () => { clearTimeout(guardTimer); for (const name of ['pointerup', 'click', 'pointercancel']) window.removeEventListener(name, block, true) }
    for (const name of ['pointerup', 'click', 'pointercancel']) window.addEventListener(name, block, true)
    guardTimer = setTimeout(() => removeGuard?.(), 1500)
  }
  emit('wake')
}
// The guard deliberately survives unmount until the wake gesture finishes (bounded to 1.5 s).
onUnmounted(() => { if (!guardTimer) removeGuard?.() })
</script>

<template>
  <main class="idle-screen" :class="{ 'idle-screen--portrait': portraitHero }" :lang="{kz:'kk',ky:'ky',uz:'uz',ru:'ru'}[language]" @pointerdown="wake">
    <header class="idle-brand">
      <img v-if="config?.brand?.logoUrl" class="idle-owner-logo" :src="config.brand.logoUrl" alt=""/><strong v-if="brandTitle(config)==='LABRIX WASH'" class="idle-wordmark">LABRIX <span>WASH</span></strong><strong v-else class="idle-wordmark custom-wordmark">{{brandTitle(config)}}</strong>
      <p>{{ brandSubtitle(config,text.descriptor) }}</p>
    </header>
    <section class="idle-hero" aria-hidden="true">
      <img v-if="!heroMissing" :src="heroSource" alt="" fetchpriority="high" draggable="false" @load="heroLoaded" @error="heroMissing = true" />
      <span v-else class="idle-asset-note">LABRIX WASH · HERO</span>
    </section>
    <section class="idle-message"><h1>{{ text.slogan }}<span>{{ text.continuation }}</span></h1></section>
    <section class="idle-action">
      <button class="idle-cta" @keydown.enter.prevent="wake" @keydown.space.prevent="wake" @click.stop="wake">
        <svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M25 34V17a5 5 0 0 1 10 0v14l3-2a4 4 0 0 1 6 3 4 4 0 0 1 7 3 4 4 0 0 1 6 4l-3 14H30L17 38a4 4 0 0 1 6-5l2 1Z"/><path d="M15 23a16 16 0 1 1 31-5M9 16l-4-2M15 6l-3-4"/></svg>
        <span><strong>{{ text.touch }}</strong><small>{{ text.subtitle }}</small></span>
      </button>
    </section>
    <footer class="idle-footer">
      <div class="idle-phones"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 3h4l2 5-3 2a15 15 0 0 0 6 6l2-3 5 2v4c0 2-2 3-4 2C9 19 5 15 3 7c-1-2 0-4 2-4Z"/></svg><span>{{config?.contacts?.supportPhone||'+998 91 111 69 29'}}</span><i></i><span>+998 91 667 62 28</span></div>
      <div class="idle-bottom">
        <div class="idle-socials">
          <span><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="m21 3-4 18-6-5-3 3 1-6 9-7-12 6-5-2Z"/></svg>Telegram</span>
          <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r=".8"/></svg>Instagram</span>
          <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 6 3-6 3Z"/></svg>YouTube</span>
          <b>@labrixwash</b>
        </div>
        <nav v-if="config?.layout?.showLanguageButtons!==false" aria-label="Language" @pointerdown.stop @click.stop @keydown.stop>
          <button v-for="lang in ['ru','uz','kz','ky']" :key="lang" :aria-label="languageNames[lang]" :aria-pressed="language === lang" :class="{ active: language === lang }" @click="emit('update:language', lang)">{{ lang.toUpperCase() }}</button>
        </nav>
      </div>
    </footer>
  </main>
</template>

<style scoped>
.idle-screen { --idle-bg:#15191d; --idle-accent:#55bdd6; width:100%; height:100dvh; overflow:hidden; display:grid; grid-template-rows:13% 51% 12% 14% 10%; background:var(--idle-bg); color:#fff; user-select:none; touch-action:manipulation; font-family:Arial,'Noto Sans',sans-serif; }
.idle-brand { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:0; padding:2vh 4vw 1vh; gap:1.2vh; background:var(--idle-bg); }
.idle-brand p { margin:0; text-align:center; color:#b8c8d6; font-size:clamp(14px,2.7vw,31px); line-height:1.3; }
.idle-wordmark { font-size:clamp(36px,8.8vw,104px); font-weight:900; letter-spacing:-.055em; line-height:1; }.idle-wordmark span { color:var(--idle-accent); }
.idle-hero { position:relative; min-height:0; overflow:hidden; background:#15191d; display:grid; place-items:center; }
.idle-hero::after { content:''; position:absolute; inset:-1px; pointer-events:none; background:linear-gradient(to bottom,var(--idle-bg) 0%,rgba(21,25,29,.75) 5%,rgba(21,25,29,.25) 13%,transparent 23%,transparent 70%,rgba(21,25,29,.22) 81%,rgba(21,25,29,.78) 94%,var(--idle-bg) 100%); }
.idle-hero img { width:100%; height:100%; object-fit:cover; object-position:center; min-height:0; }

.idle-asset-note { color:#8194a8; font-size:clamp(18px,3vw,32px); letter-spacing:.15em; }
.idle-message { display:grid; place-items:center; padding:0 4vw; text-align:center; }
h1 { margin:0; font-size:clamp(24px,5.6vw,64px); line-height:1.2; font-weight:700; letter-spacing:-.035em; }h1 span { display:block; margin-top:.7vh; color:#bac1c7; font-size:.91em; font-weight:500; }
.idle-action { display:flex; align-items:center; justify-content:center; padding:1.2vh 5vw 2vh; }
.idle-cta { display:flex; align-items:center; justify-content:center; gap:2.5vw; width:100%; height:100%; color:#f4f6f7; background:transparent; border:1px solid #59636b; border-radius:16px; }
.idle-cta svg { width:10vw; max-width:108px; padding-right:2vw; border-right:1px solid #3f494f; flex:none; color:var(--idle-accent); }.idle-cta strong { display:block; font-size:clamp(21px,4.5vw,54px); letter-spacing:.01em; }.idle-cta small { display:block; margin-top:1vh; color:#aeb9c1; font-size:clamp(16px,2.9vw,34px); }
.idle-footer { margin:0 4vw; padding:1.4vh 0; border-top:1px solid #343a40; display:flex; flex-direction:column; justify-content:space-around; gap:.8vh; }
.idle-phones { display:flex; align-items:center; justify-content:center; gap:2vw; font-size:clamp(15px,2.65vw,30px); font-variant-numeric:tabular-nums; white-space:nowrap; }.idle-phones svg { width:2.6vw; color:var(--idle-accent); }.idle-phones i { width:1px; height:1em; background:#425267; }
.idle-bottom { display:flex; align-items:center; justify-content:space-between; gap:1vw; }.idle-socials { display:flex; align-items:center; gap:1.3vw; color:#adbfce; font-size:clamp(10px,1.75vw,21px); }.idle-socials span { display:flex; align-items:center; gap:.45vw; }.idle-socials svg { width:2vw; height:2vw; }.idle-socials b { font-weight:500; color:#e6edf5; }
nav { display:flex; flex-shrink:0; }nav button { min-width:44px; min-height:56px; padding:8px .8vw; border:0; border-bottom:2px solid transparent; background:transparent; color:#aabccf; font-size:clamp(15px,2.2vw,26px); font-weight:600; }nav button.active { color:var(--idle-accent); border-bottom-color:var(--idle-accent); }
.idle-cta:active { background:#222c32; border-color:var(--idle-accent); }
.idle-cta:focus-visible { outline:3px solid var(--idle-accent); outline-offset:6px; }
/* A portrait source can fill the viewport without cropping away the car/terminal.
   Grid overlap keeps content in normal layout over a single full-height image. */
.idle-screen--portrait { grid-template-rows:13% 60% 9% 11% 7%; isolation:isolate; }
.idle-screen--portrait > * { grid-column:1; min-width:0; }
.idle-screen--portrait .idle-hero { grid-row:1 / 6; z-index:-1; }
.idle-screen--portrait .idle-hero img { object-position:center; }
.idle-screen--portrait .idle-hero::after { background:linear-gradient(180deg,rgba(9,15,20,.72) 0%,rgba(9,15,20,.42) 12%,rgba(9,15,20,.06) 28%,rgba(9,15,20,.04) 55%,rgba(9,15,20,.50) 72%,rgba(9,15,20,.88) 85%,rgba(9,15,20,.97) 100%); }
.idle-screen--portrait .idle-brand { grid-row:1; background:transparent; }
.idle-screen--portrait .idle-message { grid-row:3; }
.idle-screen--portrait .idle-message h1 { font-size:clamp(24px,5vw,56px); }
.idle-screen--portrait .idle-action { grid-row:4; padding:.8vh 5vw 1.2vh; }
.idle-screen--portrait .idle-cta { background:rgba(15,24,30,.38); border-color:#748089; }
.idle-screen--portrait .idle-cta:active { background:rgba(45,65,77,.85); border-color:var(--idle-accent); }
.idle-screen--portrait .idle-footer { grid-row:5; padding:.6vh 0; }
@media(prefers-reduced-motion:reduce) { .idle-cta { animation:none; } }
@media(max-width:600px) { .idle-bottom { flex-wrap:wrap; justify-content:center; }.idle-socials { font-size:11px; }.idle-footer { padding-bottom:4px; }nav button { min-height:44px; }.idle-screen { grid-template-rows:13% 45% 12% 16% 14%; } }
@media(max-width:600px) { .idle-screen--portrait { grid-template-rows:13% 54% 10% 12% 11%; } }
.idle-cta > span { min-width:0; }
.idle-screen[lang="uz"] .idle-cta strong { max-width:700px; font-size:clamp(22px,3.7vw,42px); line-height:1.15; text-wrap:balance; }
</style>

<style scoped>.idle-owner-logo{max-width:25vw;height:5vh;object-fit:contain}.idle-brand:has(.idle-owner-logo){gap:.4vh}.custom-wordmark{font-size:clamp(30px,6vw,70px);text-align:center;overflow-wrap:anywhere;max-width:90vw}</style>
