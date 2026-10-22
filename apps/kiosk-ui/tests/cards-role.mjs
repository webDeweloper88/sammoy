import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
const origin='http://127.0.0.1:5197',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5197','--strictPort'],{stdio:'ignore'});let browser;
try{for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
for(const [local,primary] of [[2,1],[3,1],[2,2]]){
const p=await browser.newPage({viewport:{width:1080,height:1920}}),errors=[],writes=[];p.on('pageerror',e=>errors.push(e.message));await p.addInitScript(()=>{sessionStorage.setItem('sammoy-owner-token','fixture');localStorage.setItem('sammoy-ui-language','ru')});
await p.route('**/api/**',async r=>{const path=new URL(r.request().url()).pathname;if(r.request().method()!=='GET')writes.push(path);let data;
if(path==='/api/auth/me')data={role:'owner',login:'owner',must_change_password:false};
else if(path==='/api/owner/wallet')data={configuration:{enabled:true,local_post:local,primary_post:primary,peer_urls:{1:'http://10.10.10.8',2:'http://10.10.10.7'}}};
else if(path==='/api/owner/vip-profiles')data={profiles:[{id:1,code:'VIP',name:'Test VIP',enabled:true,grant_seconds:60,max_uses_per_day:1,device_types:['wash']}]};
else if(path==='/api/owner/rfid/cards')data={cards:[{uid:'ABC123',enabled:true,status:'active',display_name:'Test'}]};
else if(path==='/api/owner/wallet/customers')data={cards:[{uid:'DEF123',enabled:true,status:'active',balance_sum:10000}],can_edit:local===primary};
else throw Error('Unexpected '+path);await r.fulfill({json:data})});
await p.goto(origin+'/owner/cards');await p.getByRole('heading',{name:'Профили',exact:true}).waitFor();
const can=local===primary;
assert.equal(await p.getByRole('button',{name:'Добавить профиль',exact:true}).isEnabled(),can);
assert.equal(await p.getByRole('button',{name:'Добавить карту',exact:true}).isEnabled(),can);
for(const button of await p.getByRole('button',{name:'Изменить',exact:true}).all())assert.equal(await button.isEnabled(),can);
assert.equal(await p.getByRole('button',{name:'Убрать VIP',exact:true}).isEnabled(),can);
if(!can){await p.locator('.cards-readonly').getByText('Только просмотр',{exact:true}).waitFor();await p.getByLabel('QR главного поста',{exact:true}).waitFor();assert.equal(await p.getByRole('button',{name:'Перенос локальных остатков',exact:true}).count(),0);}
await p.getByRole('button',{name:'Денежные карты',exact:true}).click();await p.getByText('DEF123',{exact:true}).waitFor();assert.equal(await p.getByRole('button',{name:'Изменить',exact:true}).isEnabled(),can);assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);await p.close();
}
console.log('PASS cards roles: standby and ordinary posts read-only; primary 2 can manage; VIP/customer viewing makes no writes');
}finally{await browser?.close();server.kill()}
