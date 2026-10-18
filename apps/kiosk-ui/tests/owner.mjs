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
 let savedConfig, savedProfile, savedCard, savedParameters, logout=false;let customer={uid:'ABCD',display_name:'Client',enabled:true,status:'active',balance_sum:35000,assigned_sum:0,revision:3,pending:false};let imported=false,importAttempts=0;
 let vipImported=false,vipAttempts=0,vipComplete=false,finishAttempts=0;
 let wallet={enabled:true,local_post:1,site_id:'SITE',primary_post:1,standby_post:7,visit_timeout_minutes:30,peer_urls:{},standby_ready:true,single_node:false};
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;let data={ok:true};
  if(path==='/api/auth/me')data=user;
  else if(path==='/api/owner/operator/settings')data={ok:true,settings:{enabled:false,phone:'',chat_id:''}};
  else if(path==='/api/owner/wallet')data={configuration:wallet,role:'primary',pending_count:0};
  else if(path==='/api/owner/wallet/diagnostics')data={ok:true,state:'in-sync',checked_at:'2026-10-10T12:00:00Z',nodes:[1,7].map(post=>({post,online:true,proof:{generation:1,operation_count:3,pending_count:0,journal_digest:'a'.repeat(64),state_digest:'b'.repeat(64)}}))};
  else if(path==='/api/owner/wallet/customers'){if(req.method()==='POST'){const body=req.postDataJSON();assert.equal(body.expected_revision,3);assert(!('balance_sum' in body));customer={...customer,...body,revision:4};}data={ok:true,cards:[customer],next_after:null,can_edit:true};}
  else if(path==='/api/owner/wallet/local-import'){if(req.method()==='POST'){const body=req.postDataJSON();assert.equal(body.confirmation,'IMPORT CAFE 35000');assert.equal(body.amount_sum,35000);importAttempts++;if(importAttempts===1)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Ответ кошелька потерян; повторите'})});imported=true;data={ok:true};}else data={ok:true,enabled:true,post_no:1,next_after:null,cards:imported?[]:[{uid:'CAFE',display_name:'Local client',balance_sum:35000,status:'active',enabled:!importAttempts,import_status:importAttempts?'pending':null,import_sum:importAttempts?35000:null}]};}
  else if(path==='/api/owner/wallet/vip-import'){if(req.method()==='POST'){assert.equal(req.postDataJSON().confirmation,'IMPORT VIP BEEF');vipAttempts++;if(vipAttempts===1)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'VIP reply lost'})});vipImported=true;}else data={ok:true,enabled:true,post_no:1,unstaged:0,next_after:null,cards:[{uid:'BEEF',display_name:'Local VIP',enabled:true,status:'active',profile:{code:'VIP',name:'VIP'},daily_uses:{'2026-10-12':2},visit:{remaining_sum:1000},import_status:vipImported?'done':'pending'}]};}
  else if(path==='/api/owner/wallet/vip-migration')data={ok:true,complete:vipComplete,can_finish:true,site_id:'SITE'};
  else if(path==='/api/owner/wallet/vip-migration/complete'){assert.equal(req.postDataJSON().confirmation,'COMPLETE VIP MIGRATION SITE SITE');finishAttempts++;if(finishAttempts===1)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Station 7 pending'})});vipComplete=true;}
  else if(path==='/api/owner/wallet/timeout'){wallet.visit_timeout_minutes=req.postDataJSON().visit_timeout_minutes;data={ok:true};}
  else if(path==='/api/owner/wallet/synchronize')data={ok:true};
  else if(path==='/api/owner/reports/summary')data={ok:true,summary:{cash_sum:12000,click_sum:3000,sessions:2,spent_sum:12000},modes:[{mode:'water',duration_ms:120000,spent_sum:3000}],sessions:[]};
  else if(path==='/api/owner/reports/stations')data={status:'partial',summary:{cash_amount:1000,click_amount:2000,total_amount:3000,online_posts:1},posts:[{post_id:'POST-01',name:'Post 1',status:'online',report:{cash_amount:1000,click_amount:2000,total_sessions:1}},{post_id:'POST-02',name:'Post 2',status:'offline'}]};
  else if(path==='/api/owner/wash/parameters'){if(req.method()==='POST')savedParameters=req.postDataJSON().parameters;if(!savedParameters){savedParameters=(await(await fetch('http://127.0.0.1:8090/api/wash/state')).json()).parameters;savedParameters.topUpBonus ||= {enabled:false,percent:10};}data={ok:true,parameters:savedParameters};}
  else if(path==='/api/owner/vip-profiles') { if(req.method()==='POST')savedProfile=req.postDataJSON();data={profiles:[{id:1,code:'VIP',name:'Test VIP',enabled:true,grant_seconds:60,max_uses_per_day:1,owner_notes:''}]}; }
  else if(path==='/api/owner/rfid/cards'){assert.equal(url.searchParams.get('include_inactive'),req.method()==='GET'?'true':null);if(req.method()==='POST')savedCard=req.postDataJSON();data={cards:[{uid:'ABC123',display_name:'Blocked card',vip_profile_id:1,status:'blocked',enabled:true,card_type:'vip'}]};}
  else if(path==='/api/owner/rfid/latest')data={online:true,latest:{uid:'12345678',seen_at:new Date().toISOString()}};
  else if(path==='/api/owner/kiosk/appearance'){const mode=req.postDataJSON().config.mode;savedConfig ||= structuredClone(config.config);savedConfig.theme.appearance ||= {lightStart:'08:00',lightEnd:'18:00',manualTheme:'dark'};savedConfig.theme.appearance.mode=mode==='auto'?'auto':'manual';if(mode!=='auto')savedConfig.theme.appearance.manualTheme=mode;data={ok:true,appearance:savedConfig.theme.appearance};}
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
 await page.getByRole('button',{name:'Денежные карты',exact:true}).tap();await page.locator('.customer-cards').getByText('Client',{exact:true}).waitFor();assert.equal(importAttempts,0);
 await page.locator('.customer-cards').getByRole('button',{name:'Изменить',exact:true}).tap();await page.locator('.customer-cards').getByLabel('Статус',{exact:true}).selectOption('lost');await page.locator('.customer-cards').getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByText('Карта сохранена. Денежный остаток не изменён.',{exact:true}).waitFor();assert.equal(customer.balance_sum,35000);assert.equal(customer.status,'lost');
 await page.getByRole('button',{name:'Перенос локальных остатков',exact:true}).tap();await page.getByText('Local client',{exact:true}).waitFor();assert.equal(importAttempts,0);await page.locator('.customer-cards').getByRole('button',{name:'Перенести',exact:true}).tap();assert(await page.getByRole('button',{name:'Подтвердить перенос',exact:true}).isDisabled());await page.locator('.import-confirm input').fill('IMPORT CAFE 35000');await page.getByRole('button',{name:'Подтвердить перенос',exact:true}).tap();await page.getByText('Ответ кошелька потерян; повторите',{exact:true}).waitFor();assert(!imported);await page.getByRole('button',{name:'Подтвердить перенос',exact:true}).tap();await page.getByText('Остаток перенесён в общий кошелёк.',{exact:true}).waitFor();assert(imported);assert.equal(importAttempts,2);
 await page.getByRole('button',{name:'Перенос VIP',exact:true}).tap();await page.getByText('Local VIP',{exact:false}).waitFor();assert.equal(vipAttempts,0);
 const vipPanel=page.locator('.vip-migration');assert.equal(await vipPanel.evaluate(e=>getComputedStyle(e).paddingLeft),'30px');
 for(const [lang,title] of [['uz','Mahalliy VIP ko‘chirish'],['en','Import local VIP'],['ru','Перенос локальных VIP']]){await page.locator('.language').getByRole('button',{name:lang.toUpperCase(),exact:true}).tap();await vipPanel.getByRole('heading',{name:title,exact:true}).waitFor();if(lang!=='ru')assert(!/[А-Яа-яЁё]/.test(await vipPanel.innerText()));}
 await vipPanel.getByRole('button',{name:'Перенести / повторить',exact:true}).tap();assert(await vipPanel.getByRole('button',{name:'Подтвердить перенос VIP',exact:true}).isDisabled());await vipPanel.locator('form').first().locator('input').fill('IMPORT VIP BEEF');await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await vipPanel.getByRole('button',{name:'Подтвердить перенос VIP',exact:true}).tap();await page.getByText('VIP reply lost',{exact:true}).waitFor();assert(!vipImported);await vipPanel.getByRole('button',{name:'Подтвердить перенос VIP',exact:true}).tap();await page.getByText('VIP перенесён. Дневные допуски сохранены.',{exact:true}).waitFor();assert.equal(vipAttempts,2);
 await vipPanel.locator('.completion input').fill('COMPLETE VIP MIGRATION SITE SITE');await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await vipPanel.getByRole('button',{name:'Завершить перенос VIP',exact:true}).tap();await page.getByText('Station 7 pending',{exact:true}).waitFor();assert(!vipComplete);await vipPanel.getByRole('button',{name:'Завершить перенос VIP',exact:true}).tap();await page.getByText('Перенос VIP всей мойки подтверждён.',{exact:true}).waitFor();assert(vipComplete);
 await page.screenshot({path:'../../docs/ui-owner-vip-migration.png',fullPage:true});
 await page.getByRole('button',{name:'Экран мойки',exact:true}).tap();await page.getByLabel('Название',{exact:true}).fill('Labrix');
 await page.getByRole('button',{name:'Telegram',exact:true}).tap();await page.getByRole('alertdialog').waitFor();await page.getByRole('button',{name:'Остаться',exact:true}).tap();
 await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(savedConfig.brand.name,'Labrix');assert.deepEqual(savedConfig.programs.map(({description,...p})=>p),config.config.programs.map(({description,...p})=>p));
 await page.getByLabel('Дизайн экрана',{exact:true}).selectOption('cards');await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(savedConfig.theme.design,'cards');
 await page.getByRole('button',{name:'Программы',exact:true}).tap();const subtitle=page.getByLabel('Подзаголовок · RU',{exact:true}).first();await subtitle.fill('Проверенное описание');await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(savedConfig.programs[0].description.ru,'Проверенное описание');await page.getByRole('button',{name:'Бренд и оформление',exact:true}).tap();

 await page.getByLabel('Вид экрана поста',{exact:true}).selectOption('light');await page.getByRole('status').filter({hasText:'Вид экрана поста применён'}).waitFor();assert.equal(savedConfig.theme.appearance.mode,'manual');assert.equal(savedConfig.theme.appearance.manualTheme,'light');
 assert.equal(await page.getByLabel('Светлая тема с HH',{exact:true}).count(),0);
 await page.reload();await page.getByLabel('Вид экрана поста',{exact:true}).waitFor();assert.equal(await page.getByLabel('Вид экрана поста',{exact:true}).inputValue(),'light');assert.equal(await page.getByLabel('Дизайн экрана',{exact:true}).inputValue(),'cards');
 await page.getByLabel('Вид экрана поста',{exact:true}).selectOption('auto');await page.getByRole('status').filter({hasText:'Вид экрана поста применён'}).waitFor();await page.getByLabel('Светлая тема с HH',{exact:true}).selectOption('09');await page.getByLabel('Светлая тема с mm',{exact:true}).selectOption('30');await page.getByLabel('Тёмная тема с HH',{exact:true}).selectOption('19');
 await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(savedConfig.theme.appearance.lightStart,'09:30');assert.equal(savedConfig.theme.appearance.lightEnd,'19:00');assert.equal(savedConfig.theme.appearance.mode,'auto');
 await page.getByRole('button',{name:'Telegram',exact:true}).tap();await page.getByRole('button',{name:'Найти посты автоматически'}).tap();
 await page.getByRole('button',{name:'Кошелёк',exact:true}).tap();await page.getByRole('heading',{name:'Общий кошелёк и резервный пост'}).waitFor();await page.getByLabel('Завершать визит через, минут',{exact:true}).tap();await page.locator('.touch-keyboard').getByRole('button',{name:'Очистить',exact:true}).tap();for(const d of '45')await page.locator('.touch-keyboard').getByRole('button',{name:d,exact:true}).tap();await page.getByRole('button',{name:'Готово ✓'}).tap();await page.getByRole('button',{name:'Сохранить время',exact:true}).tap();await page.getByText('Время визита сохранено. Изменение действует для новых визитов.').waitFor();assert.equal(wallet.visit_timeout_minutes,45);await page.getByRole('button',{name:'Синхронизировать и проверить'}).tap();await page.getByText('Журналы сверены. Запись на главный и резервный восстановлена.').waitFor();
 await page.getByRole('button',{name:'Проверить оба узла',exact:true}).tap();await page.getByText('Данные совпадают',{exact:true}).waitFor();assert.equal(await page.locator('.wallet-node').count(),2);
 const walletPanel=page.locator('.wallet-settings');assert.equal(await walletPanel.evaluate(e=>getComputedStyle(e).paddingLeft),'30px');assert.equal(await walletPanel.evaluate(e=>getComputedStyle(e).paddingTop),'28px');
 for(const [lang,title] of [['uz','Umumiy hamyon va zaxira post'],['en','Shared wallet and standby station'],['ru','Общий кошелёк и резервный пост']]){await page.locator('.language').getByRole('button',{name:lang.toUpperCase(),exact:true}).tap();await walletPanel.getByRole('heading',{name:title,exact:true}).waitFor();if(lang!=='ru')assert(!/[А-Яа-яЁё]/.test(await walletPanel.innerText()));assert.equal(await walletPanel.locator('input[type=number]').first().inputValue(),'45');}

 await page.getByRole('button',{name:'Параметры',exact:true}).tap();
 await page.getByLabel('Начислять бонус',{exact:true}).check();await page.getByLabel('Бонус, %',{exact:true}).tap();await page.locator('.touch-keyboard').getByRole('button',{name:'Очистить',exact:true}).tap();await page.locator('.touch-keyboard').getByRole('button',{name:'1',exact:true}).tap();await page.locator('.touch-keyboard').getByRole('button',{name:'2',exact:true}).tap();
 await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).first().tap();
 await page.getByText('Параметры сохранены',{exact:true}).waitFor();assert.deepEqual(savedParameters.topUpBonus,{enabled:true,percent:12});
 await page.locator('.language').getByRole('button',{name:'UZ',exact:true}).tap();await page.getByRole('heading',{name:'Balans to‘ldirish bonusi',exact:true}).waitFor();
 await page.locator('.language').getByRole('button',{name:'RU',exact:true}).tap();
 await page.getByRole('button',{name:'Учётная запись',exact:true}).tap();await page.getByLabel('Текущий пароль',{exact:true}).fill('current-password');await page.getByRole('button',{name:'Готово ✓',exact:true}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('status').filter({hasText:'Сохранено'}).waitFor();assert.equal(await page.evaluate(()=>sessionStorage.getItem('sammoy-owner-token')),'rotated-token');
 await page.getByRole('button',{name:'Выйти',exact:true}).tap();await page.waitForURL('**/login');assert(logout);
 assert.deepEqual(errors,[]);console.log('PASS Owner: bonus keypad/save, theme persistence/contrast, reports, blocked cards, edit profile, PN532 registration, unsaved guard, preserve config, discovery, account token rotation, logout');
}finally{await browser?.close();server.kill()}
