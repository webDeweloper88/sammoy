import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
const origin='http://127.0.0.1:5184';
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5184','--strictPort'],{stdio:'ignore'});
let browser;
try {
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const context=await browser.newContext({viewport:{width:1920,height:1080},hasTouch:true});
 await context.addInitScript(()=>sessionStorage.setItem('sammoy-owner-token','fixture-token'));
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const user={id:1,login:'owner',display_name:'Owner',role:'owner',must_change_password:false};
 const config=await (await fetch('http://127.0.0.1:8090/api/kiosk/settings')).json();
 let savedConfig, savedProfile, savedCard,logout=false;
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;let data={ok:true};
  if(path==='/api/auth/me')data=user;
  else if(path==='/api/owner/reports/summary')data={ok:true,summary:{cash_sum:12000,click_sum:3000,sessions:2,spent_sum:12000},modes:[{mode:'water',duration_ms:120000,spent_sum:3000}],sessions:[]};
  else if(path==='/api/owner/reports/stations')data={status:'partial',summary:{cash_amount:1000,click_amount:2000,total_amount:3000,online_posts:1},posts:[{post_id:'POST-01',name:'Post 1',status:'online',report:{cash_amount:1000,click_amount:2000,total_sessions:1}},{post_id:'POST-02',name:'Post 2',status:'offline'}]};
  else if(path==='/api/owner/wash/parameters')data=await(await fetch('http://127.0.0.1:8090/api/wash/state')).json();
  else if(path==='/api/owner/vip-profiles') { if(req.method()==='POST')savedProfile=req.postDataJSON();data={profiles:[{id:1,code:'VIP',name:'Test VIP',enabled:true,grant_seconds:60,max_uses_per_day:1,owner_notes:''}]}; }
  else if(path==='/api/owner/rfid/cards'){assert.equal(url.searchParams.get('include_inactive'),req.method()==='GET'?'true':null);if(req.method()==='POST')savedCard=req.postDataJSON();data={cards:[{uid:'ABC123',display_name:'Blocked card',vip_profile_id:1,status:'blocked',enabled:true,card_type:'vip'}]};}
  else if(path==='/api/owner/rfid/latest')data={online:true,latest:{uid:'12345678',seen_at:new Date().toISOString()}};
  else if(path==='/api/kiosk/settings'){if(req.method()==='POST')savedConfig=req.postDataJSON().config;data={...config,config:savedConfig||config.config};}
  else if(path==='/api/auth/account'){assert.equal(req.postDataJSON().current_password,'current-password');data={access_token:'rotated-token',user:{...user,display_name:'New owner'}};}
  else if(path==='/api/auth/logout')logout=true;
  else if(path==='/api/owner/telegram-setup/status')data={ok:true,configured:false,identity_configured:true,posts:[{id:'POST-01',name:'Post 1',host:'127.0.0.1'}]};
  else if(path==='/api/owner/telegram-setup/discover')data={ok:true,count:1};
  else throw Error('Unexpected API '+path);
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto(origin+'/owner/reports');await page.getByText('12 000',{exact:true}).first().waitFor();
 await page.getByRole('button',{name:'Сменить тему'}).tap();
 assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'dark');
 assert.equal(await page.locator('.card').first().evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(30, 36, 45)');
 await page.reload();await page.getByRole('heading',{name:'Отчёты',exact:true}).waitFor();assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'dark');
 await page.screenshot({path:'../../docs/ui-owner-reports-dark-1920.png',fullPage:true});
 await page.getByRole('button',{name:'Все посты',exact:true}).tap();await page.getByText('Не все посты доступны. Итог включает только ответившие посты.').waitFor();await page.getByRole('rowheader',{name:'Post 2',exact:true}).waitFor();
 await page.getByRole('button',{name:'Этот пост',exact:true}).tap();
 await page.getByRole('button',{name:'VIP и карты',exact:true}).tap();await page.getByText('Blocked card',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Изменить',exact:true}).first().tap();
 await page.getByLabel('Название',{exact:true}).fill('Changed VIP');
 await page.getByRole('button',{name:'Сохранить профиль',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(savedProfile.profiles[0].name,'Changed VIP');
 await page.getByRole('button',{name:'Добавить карту',exact:true}).tap();await page.getByRole('button',{name:'Считать PN532',exact:true}).tap();await page.waitForFunction(()=>document.querySelector('input[maxlength="64"]')?.value==='12345678');
 await page.getByRole('button',{name:'Сохранить карту',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(savedCard.uid,'12345678');
 await page.getByRole('button',{name:'Экран мойки',exact:true}).tap();await page.getByLabel('Название',{exact:true}).fill('Labrix');
 await page.getByRole('button',{name:'Telegram',exact:true}).tap();await page.getByRole('alertdialog').waitFor();await page.getByRole('button',{name:'Остаться',exact:true}).tap();
 await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(savedConfig.brand.name,'Labrix');assert.deepEqual(savedConfig.programs,config.config.programs);
 await page.getByRole('button',{name:'Telegram',exact:true}).tap();await page.getByRole('button',{name:'Найти посты автоматически'}).tap();
 await page.getByRole('button',{name:'Учётная запись',exact:true}).tap();await page.getByLabel('Текущий пароль',{exact:true}).fill('current-password');await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(await page.evaluate(()=>sessionStorage.getItem('sammoy-owner-token')),'rotated-token');
 await page.getByRole('button',{name:'Выйти',exact:true}).tap();await page.waitForURL('**/login');assert(logout);
 assert.deepEqual(errors,[]);console.log('PASS Owner: theme persistence/contrast, reports, blocked cards, edit profile, PN532 registration, unsaved guard, preserve config, discovery, account token rotation, logout');
}finally{await browser?.close();server.kill()}
