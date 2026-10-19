import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
const origin='http://127.0.0.1:5186';
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5186','--strictPort'],{stdio:'ignore'});
let browser;
try{
for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const context=await browser.newContext({viewport:{width:1920,height:1080},hasTouch:true});
await context.addInitScript(()=>sessionStorage.setItem('sammoy-owner-token','fixture'));
const page=await context.newPage(),errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));
let names=['water','osmos','nano','foam','wax','chem','vacuum','air'];
let deviceType='wash',credit=1744,pending=null,offline=false;
const diag=()=>({state:{deviceType,creditSum:credit,phase:'idle',lastRfidResult:'card_rejected',lastRfidProcessedAt:'2026-10-03T00:00:00Z',activeSessionCardUid:'private-uid'},simulation:{totalStopActive:null,coinPulses:0,licenseMode:'real'},parameters:{billPulseSum:1000},system:{disk_free_bytes:1000000000,temperature_c:44},io:{available:true,data:{modbus_ok:true,outputs:Object.fromEntries(names.map(n=>[n,false])),inputs:{total_stop:true},raw_inputs:[1,1,0,1,1,1,1,1],nv9_pulses:12}},configuration:{available:true,data:{transport:{device:'/dev/ttyUSB0',baud_rate:9600},inputs:Array.from({length:8},(_,i)=>({address:i,name:i===2?'total_stop':'di'+(i+1)})),outputs:names.map((name,address)=>({name,address})),bill_acceptor:{gpio_chip:'/dev/gpiochip0',gpio_line:33},nv9_listener_alive:true}},rfid:{available:true,data:{online:true,bus:7,firmware:'1.6.7',latest:{uid:'private-uid'},present:false}}});
const connection={hardware:{complete:true,wlan0_mac_present:true,microsd_cid_present:true,hardware_fingerprint_hash:'fixture-fingerprint'},license:{state:'valid',reason:'fixture decision',last_error:'fixture network timeout',grace_until:'2026-10-15T00:00:00Z',hardware_bound:true},license_settings:{site_code:'SITE',post_no:1,gateway_url:'https://example.test',enabled:false,sync_interval_seconds:43200,grace_seconds:604800},click_settings:{enabled:false,min_amount_sum:1000,max_amount_sum:10000000}};
await page.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;let data={ok:true};
 if(req.method()==='POST')posts.push([path,req.postDataJSON()]);
 if(path==='/api/auth/me')data={login:'admin',role:'admin',must_change_password:false};
 else if(path==='/api/admin/diagnostics'){if(offline){await route.fulfill({status:503,body:'{"detail":"offline"}'});return}data=diag()}
 else if(path==='/api/admin/manufacturer/settings')data={settings:{marketing:'',programmer:'',electrician:'',telegram:'https://t.me/labrixwash',instagram:'https://instagram.com/labrixwash',youtube:'https://youtube.com/@labrixwash'}};
 else if(path==='/api/admin/wallet')data={configuration:{enabled:false,local_post:1,site_id:'SITE',primary_post:1,standby_post:7,visit_timeout_minutes:30,peer_urls:{}}};
 else if(path==='/api/admin/install/status')data=connection;
 else if(path.startsWith('/api/admin/network/')){
  if(path.endsWith('/apply'))pending={id:'checkpoint-test',interface:'eth0',expires_at:Date.now()/1000+90};
  if(path.endsWith('/confirm')||path.endsWith('/rollback'))pending=null;
  data={ok:true,pending,interfaces:[{interface:'eth0',connected:true,address:'10.10.10.8',prefix:24,gateway:'10.10.10.1',mode:'dhcp',primary:true,dns:['10.10.10.1']},{interface:'wlan0',connected:false,mode:'dhcp'}]};
  if(path.endsWith('/wifi'))data={networks:[{ssid:'WashWiFi',signal:80,security:'wpa-psk'}]};
 }
 else if(path==='/api/admin/service/storage')data={ok:true,disk_total_bytes:32*1024**3,disk_free_bytes:1.5*1024**3,free_percent:4.7,database_bytes:9000000,level:'critical',events:{count:35},protected_credit:{amount_sum:1744},retention:{financial_months:12,event_months:1,journal_limit_mb:256,last_run:{last_run_at:new Date().toISOString(),ok:true}}};
 else if(path==='/api/admin/service/click-payments'){const q=new URL(req.url()).searchParams;const older=q.has('before_id');data={intents:[{id:older?'older-payment':'current-payment',created_at:new Date().toISOString(),amount_sum:12000,status:q.get('status')==='all'?'credited':q.get('status'),gateway_status:'paid'}],summary:[{status:'credited',count:1,amount_sum:12000}],has_more:!older,next_cursor:older?null:{before_time:'2026-10-01T00:00:00Z',before_id:'older-id'}};}
 else if(path==='/api/admin/service/events')data={events:[{id:4,created_at:new Date().toISOString(),level:'info',event_type:'boot',message:'System ready'}],has_more:false};
 else if(path==='/api/admin/service/recovery')data={credits:[]};
 else if(path==='/api/admin/service/money-input')data={parameters:{billPulseSum:2000}};
 else if(path==='/api/admin/service/outputs/water/test')data={ok:true,actual:false};
 else if(path==='/api/admin/service/all-off')data={ok:true};
 else throw Error('Unexpected API '+path);
 await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
await page.goto(origin+'/admin/diagnostics');await page.getByText('private-uid',{exact:true}).waitFor();assert.equal(posts.length,0);
for(const label of ['Параметры','VIP и карты','Экран мойки','Telegram'])assert.equal(await page.getByRole('navigation').getByRole('button',{name:label,exact:true}).count(),0);
await page.getByText('Карта заблокирована или отключена',{exact:true}).waitFor();
assert(await page.getByRole('button',{name:'Тест 1 с',exact:true}).first().isDisabled());assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.screenshot({path:'../../docs/ui-admin-diagnostics-1920.png',fullPage:true});
credit=0;await page.getByRole('button',{name:'Обновить',exact:true}).tap();await page.getByRole('button',{name:'Тест 1 с',exact:true}).first().tap();assert.equal(posts.length,0);
await page.getByRole('button',{name:'Подтвердить',exact:true}).tap();await page.getByText('Тест завершён, выключение подтверждено',{exact:true}).waitFor();assert.deepEqual(posts.at(-1),['/api/admin/service/outputs/water/test',{confirmation:'water'}]);
offline=true;await page.getByRole('button',{name:'Обновить',exact:true}).tap();await page.getByRole('alert').filter({hasText:'offline'}).waitFor();assert(await page.getByRole('button',{name:'Тест 1 с',exact:true}).first().isDisabled());offline=false;
await page.getByRole('button',{name:'Подключение',exact:true}).tap();await page.getByRole('heading',{name:'Сеть поста'}).waitFor();await page.getByText('fixture-fingerprint',{exact:true}).waitFor();
await page.getByRole('radio',{name:'Статический IP',exact:true}).check();await page.getByLabel('IP',{exact:true}).fill('10.10.10.20');await page.getByRole('button',{name:'Готово ✓'}).tap();
await page.getByRole('button',{name:'Обслуживание',exact:true}).tap();await page.getByRole('button',{name:'Остаться',exact:true}).tap();
await page.getByRole('button',{name:'Применить сеть',exact:true}).tap();await page.getByRole('button',{name:'Применить',exact:true}).tap();await page.getByRole('button',{name:'Связь работает — сохранить',exact:true}).tap();await page.getByText('Сеть сохранена',{exact:true}).waitFor();assert.deepEqual(posts.at(-1),['/api/admin/network/confirm',{id:'checkpoint-test'}]);
await page.getByLabel(/^Подключение/).selectOption('wlan0');await page.getByRole('button',{name:'Найти Wi-Fi',exact:true}).tap();await page.getByRole('button',{name:'WashWiFi · 80%'}).tap();assert.equal(await page.getByLabel('Название Wi-Fi',{exact:true}).inputValue(),'WashWiFi');
await page.getByLabel('Пароль Wi-Fi',{exact:true}).tap();await page.locator('.touch-keyboard').waitFor();await page.getByRole('button',{name:'Готово ✓'}).tap();await page.getByRole('button',{name:'Обслуживание',exact:true}).tap();await page.getByRole('button',{name:'Не сохранять',exact:true}).tap();await page.getByText('System ready',{exact:true}).waitFor();
await page.getByRole('heading',{name:'Память и хранение данных'}).waitFor();await page.getByRole('alert').filter({hasText:'Критически мало'}).waitFor();await page.getByText('12 месяцев',{exact:true}).waitFor();
await page.getByRole('button',{name:'Сменить тему'}).tap();await page.screenshot({path:'../../docs/ui-admin-maintenance-dark-1920.png',fullPage:true});
const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать диагностику',exact:true}).tap();const download=await downloadPromise;const stream=await download.createReadStream();let text='';for await(const chunk of stream)text+=chunk;assert(!text.includes('private-uid'));
await page.getByLabel('Сум за импульс',{exact:true}).tap();await page.locator('.touch-keyboard').getByRole('button',{name:'Очистить',exact:true}).tap();for(const digit of '2000')await page.locator('.touch-keyboard').getByRole('button',{name:digit,exact:true}).tap();assert.equal(await page.getByLabel('Сум за импульс',{exact:true}).inputValue(),'2000');await page.getByRole('button',{name:'Готово ✓'}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('button',{name:'Подтвердить',exact:true}).tap();await page.getByText('Стоимость импульса сохранена',{exact:true}).waitFor();assert.deepEqual(posts.at(-1),['/api/admin/service/money-input',{bill_pulse_sum:2000}]);
await page.getByRole('button',{name:'Лицензия',exact:true}).tap();await page.getByText('fixture network timeout',{exact:true}).waitFor();await page.getByText('Рекомендуемая синхронизация до',{exact:true}).waitFor();
await page.getByLabel('Подписанный код лицензии',{exact:true}).fill('unsaved-offline-code-123456');await page.getByRole('button',{name:'Готово ✓'}).tap();await page.getByRole('button',{name:'Click',exact:true}).tap();await page.getByRole('button',{name:'Не сохранять',exact:true}).tap();await page.getByText('current-payment',{exact:true}).waitFor();
await page.getByRole('button',{name:'Показать более ранние',exact:true}).tap();await page.getByText('older-payment',{exact:true}).waitFor();await page.getByLabel(/^Статус платежа/).selectOption('paid');await page.getByRole('cell',{name:'Оплачен, не зачислен',exact:true}).waitFor();assert.equal(await page.getByText('older-payment',{exact:true}).count(),0);
await page.screenshot({path:'../../docs/ui-admin-click-dark-1920.png',fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.goto(origin+'/owner/parameters');await page.waitForURL('**/admin/diagnostics');
deviceType='dry_fog';credit=0;names=['aroma_1','aroma_2','aroma_3','aroma_4','aroma_5','blackening','tank_air','purge'];await page.getByRole('button',{name:'Обновить',exact:true}).tap();await page.getByRole('cell',{name:'SHEIKH SULTAN',exact:true}).waitFor();assert.equal(await page.getByRole('rowheader',{name:'IN3',exact:true}).count(),1);assert.equal(await page.getByRole('cell',{name:'Не используется',exact:true}).count(),8);assert.equal(await page.getByText('Курок / Total Stop',{exact:true}).count(),0);await page.getByRole('row').filter({has:page.getByRole('cell',{name:'Очистка / продувка',exact:true})}).getByRole('button').tap();await page.getByRole('heading',{name:'Включить на 1 секунду: Очистка / продувка',exact:true}).waitFor();await page.getByRole('button',{name:'Отмена',exact:true}).tap();
assert.deepEqual(errors,[]);console.log('PASS Admin: routing, idle/stale guards, relay confirmation, network confirmation, Wi-Fi keyboard, dirty guard, diagnostic redaction, maintenance and themes');
}finally{await browser?.close();server.kill()}
