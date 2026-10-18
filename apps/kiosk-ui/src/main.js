import { createApp } from 'vue'
import App from './App.vue'
import InstallPage from './InstallPage.vue'
import IdlePreview from './kiosk/IdlePreview.vue'
import WashScreen from './kiosk/WashScreen.vue'
import './style.css'
import './touch.css'
import './owner.css'

if (['/', '/wash', '/preview/idle'].includes(location.pathname)) {
  const preload = document.createElement('link')
  preload.rel = 'preload'
  preload.as = 'image'
  preload.href = '/branding/labrixwash_idle_portrait.webp'
  document.head.appendChild(preload)
}

if (['/', '/wash', '/preview/wash'].includes(location.pathname)) {
  document.title = 'LABRIX WASH'
  document.documentElement.classList.add('customer-kiosk')
}

const root = ['/', '/wash', '/preview/wash'].includes(location.pathname) ? WashScreen : location.pathname === '/preview/idle' ? IdlePreview : location.pathname === '/install' ? InstallPage : App
createApp(root,root===WashScreen?{preview:location.pathname==='/preview/wash'}:{}).mount('#app')
