import {createApp,h} from 'vue'
import Telegram from '../src/TelegramConnection.vue'
import Wallet from '../src/WalletSettings.vue'
const p=new URLSearchParams(location.search)
createApp({render:()=>h(p.get('kind')==='wallet'?Wallet:Telegram,{
 language:p.get('lang')||'ru',owner:true,authToken:'fixture-owner',token:'fixture-owner',install:p.get('kind')==='wallet'
})}).mount('#app')
