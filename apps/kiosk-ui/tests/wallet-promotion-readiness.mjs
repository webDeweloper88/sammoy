import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
const origin='http://127.0.0.1:5198',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5198','--strictPort'],{stdio:'ignore'});let browser;
try{for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
for(const ready of [false,true]){
 const p=await browser.newPage(),errors=[],writes=[];p.on('pageerror',e=>errors.push(e.message));const cfg={enabled:true,local_post:2,primary_post:1,standby_post:2,standby_ready:ready,generation:1,peer_urls:{1:'http://10.10.10.8',2:'http://10.10.10.7'}};
 await p.route('**/promotion-test',r=>r.fulfill({contentType:'text/html',body:`<div id="app"></div><script type="module">import {createApp} from '/node_modules/.vite/deps/vue.js';import Wallet from '/src/WalletSettings.vue';createApp(Wallet,{token:'fixture',language:'ru'}).mount('#app')</script>`}));
 await p.route('**/api/**',async r=>{const path=new URL(r.request().url()).pathname;if(r.request().method()!=='GET')writes.push(path);let data;
 if(path==='/api/wallet-management/status')data={ok:true,configuration:cfg};
 else if(path==='/api/owner/wallet')data={role:'standby',configuration:cfg};
 else if(path==='/api/owner/wallet/availability')data={checked_at:new Date().toISOString(),nodes:[{post:1,state:'unavailable'},{post:2,state:'available'}]};
 else if(path==='/api/owner/device-policy')data={policy:null,configuration:cfg};
 else if(path==='/api/wash/state')data={parameters:{topUpBonus:{enabled:false,percent:10},freePauseSeconds:60}};
 else if(path==='/api/owner/device')data={active_type:'wash',requested:{type:'wash'}};
 else throw Error(path);await r.fulfill({json:data})});
 await p.goto(origin+'/promotion-test');await p.getByText('Главный пост неисправен?',{exact:true}).click();
 const button=p.getByRole('button',{name:'Восстановить работу на этом посту',exact:true});
 assert.equal(await button.isEnabled(),ready);
 if(!ready)await p.getByText('Этот резерв ещё не готов к восстановлению: сначала нужна полная синхронизация на главном.',{exact:true}).waitFor();
 else{await button.click();const proceed=p.getByRole('button',{name:'Проверить и продолжить',exact:true});assert(await proceed.isDisabled());await p.getByLabel('Прежний главный физически отключён',{exact:true}).check();assert(await proceed.isDisabled());await p.getByLabel('Понимаю: до восстановления резерва данные будут храниться на одном серверном посту',{exact:true}).check();assert(await proceed.isEnabled());}
 assert.equal(await p.getByText(/PROMOTE POST/).count(),0);
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);await p.close();
}
console.log('PASS promotion readiness: unverified standby cannot recover; physical fencing and single-copy acceptance required; verified standby enables switch even with primary offline; no writes');
}finally{await browser?.close();server.kill()}
