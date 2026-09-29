import { createApp } from 'vue'
import App from './App.vue'
import InstallPage from './InstallPage.vue'
import './style.css'
import './touch.css'
import './owner.css'

createApp(location.pathname === '/install' ? InstallPage : App).mount('#app')
