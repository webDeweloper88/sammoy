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
const names=['water','osmos','nano','foam','wax','chem','vacuum','air'];
let credit=1744,pending=null,offline=false;
const diag=()=>({state:{creditSum:credit,phase:'idle',activeSessionCardUid:'private-uid'},simulation:{totalStopActive:null},parameters:{billPulseSum:1000},system:{disk_free_bytes:1000000000,temperature_c:44},io:{available:true,data:{modbus_ok:true,outputs:Object.fromEntries(names.map(n=>[n,false])),inputs:{total_stop:true},raw_inputs:[1,1,0,1,1,1,1,1],nv9_pulses:12}},configuration:{available:true,data:{transport:{device:'/dev/ttyUSB0',baud_rate:9600},inputs:Array.from({length:8},(_,i)=>({address:i,name:i===2?'total_stop':'di'+(i+1)})),outputs:names.map((name,address)=>({name,address})),bill_acceptor:{gpio_chip:'/dev/gpiochip0',gpio_line:33},nv9_listener_alive:true}},rfid:{available:true,data:{online:true,bus:7,firmware:'1.6.7',latest:{uid:'private-uid'},present:false}}});
const connection={license:{state:'disabled'},license_settings:{site_code:'SITE',post_no:1,gateway_url:'https://example.test',enabled:false,sync_interval_seconds:43200,grace_seconds:604800},click_settings:{enabled:false,min_amount_sum:1000,max_amount_sum:10000000}};
await page.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;let data={ok:true};
 if(req.method()==='POST')posts.push([path,req.postDataJSON()]);
 if(path==='/api/auth/me')data={login:'admin',role:'admin',must_change_password:false};
 else if(path==='/api/admin/diagnostics'){if(offline){await route.fulfill({status:503,body:'{"detail":"offline"}'});return}data=diag()}
 else if(path==='/api/admin/install/status')data=connection;
 else if(path.startsWith('/api/admin/network/')){
  if(path.endsWith('/apply'))pending={id:'checkpoint-test',interface:'eth0',expires_at:Date.now()/1000+90};
  if(path.endsWith('/confirm')||path.endsWith('/rollback'))pending=null;
  data={ok:true,pending,interfaces:[{interface:'eth0',connected:true,address:'10.10.10.8',prefix:24,gateway:'10.10.10.1',mode:'dhcp',primary:true,dns:['10.10.10.1']},{interface:'wlan0',connected:false,mode:'dhcp'}]};
  if(path.endsWith('/wifi'))data={networks:[{ssid:'WashWiFi',signal:80,security:'wpa-psk'}]};
 }
 else if(path==='/api/admin/service/events')data={events:[{id:4,created_at:new Date().toISOString(),level:'info',event_type:'boot',message:'System ready'}],has_more:false};
 else if(path==='/api/admin/service/recovery')data={credits:[]};
 else if(path==='/api/admin/service/money-input')data={parameters:{billPulseSum:2000}};
 else if(path==='/api/admin/service/outputs/water/test')data={ok:true,actual:false};
 else if(path==='/api/admin/service/all-off')data={ok:true};
 else throw Error('Unexpected API '+path);
 await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
await page.goto(origin+'/admin/diagnostics');await page.getByText('private-uid',{exact:true}).waitFor();assert.equal(posts.length,0);
assert(await page.getByRole('button',{name:'Тест 1 с',exact:true}).first().isDisabled());assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.screenshot({path:'../../docs/ui-admin-diagnostics-1920.png',fullPage:true});
credit=0;await page.getByRole('button',{name:'Обновить',exact:true}).tap();await page.getByRole('button',{name:'Тест 1 с',exact:true}).first().tap();assert.equal(posts.length,0);
await page.getByRole('button',{name:'Подтвердить',exact:true}).tap();await page.getByText('Тест завершён, выключение подтверждено',{exact:true}).waitFor();assert.deepEqual(posts.at(-1),['/api/admin/service/outputs/water/test',{confirmation:'water'}]);
offline=true;await page.getByRole('button',{name:'Обновить',exact:true}).tap();await page.getByRole('alert').filter({hasText:'offline'}).waitFor();assert(await page.getByRole('button',{name:'Тест 1 с',exact:true}).first().isDisabled());offline=false;
await page.getByRole('button',{name:'Подключение',exact:true}).tap();await page.getByRole('heading',{name:'Сеть Radxa'}).waitFor();
await page.getByLabel('Адрес IPv4',{exact:true}).selectOption('static');await page.getByLabel('IP',{exact:true}).fill('10.10.10.20');await page.getByRole('button',{name:'Готово ✓'}).tap();
await page.getByRole('button',{name:'Обслуживание',exact:true}).tap();await page.getByRole('button',{name:'Остаться',exact:true}).tap();
await page.getByRole('button',{name:'Применить сеть',exact:true}).tap();await page.getByRole('button',{name:'Применить',exact:true}).tap();await page.getByRole('button',{name:'Связь работает — сохранить',exact:true}).tap();await page.getByText('Сеть сохранена',{exact:true}).waitFor();assert.deepEqual(posts.at(-1),['/api/admin/network/confirm',{id:'checkpoint-test'}]);
await page.getByLabel('Подключение',{exact:true}).selectOption('wlan0');await page.getByRole('button',{name:'Найти Wi-Fi',exact:true}).tap();await page.getByRole('button',{name:'WashWiFi · 80%'}).tap();assert.equal(await page.getByLabel('Название Wi-Fi',{exact:true}).inputValue(),'WashWiFi');
await page.getByLabel('Пароль Wi-Fi',{exact:true}).tap();await page.locator('.touch-keyboard').waitFor();await page.getByRole('button',{name:'Готово ✓'}).tap();await page.getByRole('button',{name:'Обслуживание',exact:true}).tap();await page.getByRole('button',{name:'Не сохранять',exact:true}).tap();await page.getByText('System ready',{exact:true}).waitFor();
await page.getByRole('button',{name:'Сменить тему'}).tap();await page.screenshot({path:'../../docs/ui-admin-maintenance-dark-1920.png',fullPage:true});
const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать диагностику',exact:true}).tap();const download=await downloadPromise;const stream=await download.createReadStream();let text='';for await(const chunk of stream)text+=chunk;assert(!text.includes('private-uid'));
await page.getByLabel('Сум за импульс',{exact:true}).fill('2000');await page.getByRole('button',{name:'Готово ✓'}).tap();await page.getByRole('button',{name:'Сохранить',exact:true}).tap();await page.getByRole('button',{name:'Подтвердить',exact:true}).tap();await page.getByText('Стоимость импульса сохранена',{exact:true}).waitFor();assert.deepEqual(posts.at(-1),['/api/admin/service/money-input',{bill_pulse_sum:2000}]);
assert.deepEqual(errors,[]);console.log('PASS Admin: routing, idle/stale guards, relay confirmation, network confirmation, Wi-Fi keyboard, dirty guard, diagnostic redaction, maintenance and themes');
}finally{await browser?.close();server.kill()}
