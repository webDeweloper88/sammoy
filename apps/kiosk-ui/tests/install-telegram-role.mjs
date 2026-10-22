import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
const origin='http://127.0.0.1:5205',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5205','--strictPort'],{stdio:'ignore'});let browser;
try{
for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
for(const [local,primary] of [[2,1],[3,1],[2,2]]){
const page=await browser.newPage({viewport:{width:1080,height:1920}}),errors=[],writes=[],telegramCalls=[];page.on('pageerror',e=>errors.push(e.message));const standby=primary===1?2:1,peers={1:'http://10.10.10.8',2:'http://10.10.10.7',3:'http://10.10.10.6'},cfg={enabled:true,site_id:'TEST',local_post:local,primary_post:primary,standby_post:standby,generation:1,visit_timeout_minutes:30,peer_urls:peers};
await page.route('**/api/**',async r=>{const req=r.request(),path=new URL(req.url()).pathname;if(req.method()!=='GET')writes.push(path);if(path.includes('/telegram/'))telegramCalls.push(path);let data;
if(path==='/api/commissioning/state')data={complete:false};
else if(path==='/api/commissioning/status')data={commissioning:{complete:false},hardware:{complete:true},io_ready:true,site:{site_code:'TEST',post_no:local,gateway_url:'https://pay.labrix.uz'},license:{locked:false}};
else if(path==='/api/wash/state')data={state:{creditSum:0},parameters:{freePauseSeconds:60,topUpBonus:{enabled:false,percent:10}}};
else if(path==='/api/commissioning/wallet')data={role:local===primary?'primary':local===standby?'standby':'post',configuration:cfg,pending_count:0};
else if(path==='/api/commissioning/wallet/availability')data={checked_at:new Date().toISOString(),nodes:[],primary_post:primary,standby_post:standby,generation:1};
else if(path==='/api/commissioning/device-policy')data={policy:null,configuration:cfg};
else if(path==='/api/commissioning/device')data={active_type:'wash',requested:{type:'wash'}};
else if(path==='/api/commissioning/network/status')data={pending:null,interfaces:[{interface:'eth0',connected:true,address:new URL(peers[local]).hostname,prefix:24}]};
else if(path==='/api/commissioning/internet')data={reachable:true};
else throw Error(path);await r.fulfill({json:data});
});
await page.goto(origin+'/install');await page.getByRole('button',{name:'Продолжить',exact:true}).click();await page.getByRole('button',{name:'Продолжить',exact:true}).click();
if(local!==primary){await page.getByRole('heading',{name:'Telegram управляется на главном посту №'+primary,exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Подключить сейчас',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Настроить позже в Owner',exact:true}).count(),0);assert.equal(await page.getByLabel('BotFather token',{exact:true}).count(),0);assert.equal(await page.getByRole('heading',{name:'Временный интернет для установки',exact:true}).count(),0);assert.equal(await page.getByRole('link',{name:'Открыть Telegram на главном посту',exact:true}).count(),0);await page.getByLabel('QR главного поста',{exact:true}).waitFor();await page.getByRole('button',{name:'Продолжить',exact:true}).click();await page.getByRole('heading',{name:'Проверка перед запуском',exact:true}).waitFor();}
else await page.getByRole('button',{name:'Подключить сейчас',exact:true}).waitFor();
assert.deepEqual(writes,[]);assert.deepEqual(telegramCalls,[]);assert.deepEqual(errors,[]);await page.close();}
console.log('PASS Telegram role step: standby and ordinary posts show primary info only; continue without token or bot calls; a promoted primary still offers setup');
}finally{await browser?.close();server.kill()}
