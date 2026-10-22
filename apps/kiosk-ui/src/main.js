import { createApp } from 'vue'
import App from './App.vue'
import InstallPage from './InstallPage.vue'
import IdlePreview from './kiosk/IdlePreview.vue'
import WashScreen from './kiosk/WashScreen.vue'
import './style.css'
import './touch.css'
import './owner.css'
import {enableManagementScroll} from './management-scroll.js'

const path=location.pathname.replace(/\/+$/,'')||'/'

if (['/', '/wash', '/preview/idle'].includes(path)) {
  const preload = document.createElement('link')
  preload.rel = 'preload'
  preload.as = 'image'
  preload.href = '/branding/labrixwash_idle_portrait.webp'
  document.head.appendChild(preload)
}

if (['/', '/wash', '/preview/wash', '/preview/dry-fog'].includes(path)) {
  document.title = path==='/preview/dry-fog'?'LABRIX AROMA':'LABRIX WASH'
  document.documentElement.classList.add('customer-kiosk')
}

const root = ['/', '/wash', '/preview/wash', '/preview/dry-fog'].includes(path) ? WashScreen : path === '/preview/idle' ? IdlePreview : path === '/install' ? InstallPage : App
if(root===App||root===InstallPage)enableManagementScroll()
async function mount(){
 if(root===WashScreen&&!['/preview/wash','/preview/dry-fog'].includes(path)){
  try{
   const response=await fetch('/api/commissioning/state',{cache:'no-store',signal:AbortSignal.timeout(5000)})
   if(!response.ok)throw Error('Setup state unavailable')
   const state=await response.json()
   if(state.complete!==true){if(state.complete===false)location.replace('/install');else location.replace('/launch');return}
  }catch{location.replace('/launch');return}
 }
 createApp(root,root===WashScreen?{preview:['/preview/wash','/preview/dry-fog'].includes(path),previewKind:path==='/preview/dry-fog'?'dry_fog':'wash'}:{}).mount('#app')
}
mount()
