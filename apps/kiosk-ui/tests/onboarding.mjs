import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5194',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5194','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:390,height:844},hasTouch:true});page.setDefaultTimeout(10000)
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)})
 let configured=false,paired=false,allowed=true,phoneCalls=0,pairCalls=0,replacements=0
 await page.route('**/__onboarding?*',route=>route.fulfill({contentType:'text/html',body:`<div id="app"></div><script type="module" src="/tests/onboarding-fixture.js"></script>`}))
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;let data={ok:true}
  if(path.includes('/owner/telegram-setup/'))assert.equal(req.headers().authorization,'Bearer fixture-owner')
  if(path.endsWith('/telegram-setup/status'))data={configured,enabled:configured,owner_paired:paired,bot_username:'fixture_bot',manage_allowed:allowed,primary_post:1,primary_url:'http://10.10.10.26',identity_configured:true}
  else if(path.endsWith('/mobile/network')||path.endsWith('/network/status'))data={interfaces:[{interface:'eth0',connected:true,address:'10.10.10.26'},{interface:'wlan0',connected:true,address:'192.168.43.8'}]}
  else if(path.endsWith('/mobile/session')){assert.equal(req.postDataJSON().interface,'wlan0');phoneCalls++;data={mobile_url:'http://192.168.43.8/api/telegram-setup/mobile/fixture',expires_at:new Date(Date.now()+600000).toISOString(),qr_data_url:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg"/>')}}
  else if(path.endsWith('/telegram-setup/configure-auto')){assert.equal(req.postDataJSON().token,'fixture:replacement');replacements++;data={ok:true}}
  else if(path.endsWith('/telegram-setup/pairing')){assert.equal(req.postDataJSON().reset_owner,false);pairCalls++;data={qr_data_url:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg"/>')}}
  else if(path==='/api/commissioning/wallet')data={configuration:{enabled:false,site_id:'fixture',local_post:1,primary_post:1,standby_post:2,peer_urls:{},visit_timeout_minutes:30}}
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 for(const [lang,label] of [['ru','Как подключить'],['uz','Qanday ulash kerak'],['en','How to connect']])for(const kind of ['telegram','wallet']){
  await page.goto(origin+'/__onboarding?lang='+lang+'&kind='+kind)
  console.log('Checking help',lang,kind);const help=page.getByRole('button',{name:'ⓘ '+label,exact:true});await help.click()
  const modal=page.getByRole('dialog');await modal.waitFor();assert(await modal.locator('li').count()>=5)
  await page.keyboard.press('Escape');await modal.waitFor({state:'hidden'});assert(await help.evaluate(e=>e===document.activeElement))
 }
 await page.goto(origin+'/__onboarding?kind=telegram&lang=ru');assert.equal(await page.getByLabel('BotFather token',{exact:true}).count(),0)
 await page.getByLabel('Сеть телефона',{exact:true}).selectOption('wlan0');await page.getByRole('button',{name:'Настроить с телефона',exact:true}).click()
 await page.getByText('Одноразовая ссылка · 10 минут',{exact:true}).waitFor();assert.equal(phoneCalls,1)
 assert.equal(await page.getByRole('link',{name:'Открыть страницу настройки'}).getAttribute('href'),'http://192.168.43.8/api/telegram-setup/mobile/fixture')
 configured=true;await page.getByRole('button',{name:'Обновить статус',exact:true}).click();await page.getByRole('button',{name:'Привязать владельца',exact:true}).click()
 await page.getByAltText('Telegram QR',{exact:true}).waitFor();assert.equal(pairCalls,1)
 paired=true;await page.getByRole('button',{name:'Обновить статус',exact:true}).click();await page.getByRole('status').filter({hasText:'Владелец привязан'}).waitFor();assert.equal(await page.getByAltText('Telegram QR',{exact:true}).count(),0)
 await page.getByRole('button',{name:'Отключить бота',exact:true}).click();await page.getByRole('alertdialog').waitFor();await page.getByRole('button',{name:'Отмена',exact:true}).click();await page.getByRole('alertdialog').waitFor({state:'hidden'})
 await page.getByRole('button',{name:'Ввести токен на этом экране',exact:true}).click();await page.getByLabel('BotFather token',{exact:true}).fill('fixture:replacement');await page.getByRole('button',{name:'Проверить и подключить',exact:true}).click();await page.getByRole('alertdialog').waitFor();assert.equal(replacements,0);await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByRole('alertdialog').waitFor({state:'hidden'});assert.equal(replacements,1);assert.equal(await page.getByLabel('BotFather token',{exact:true}).count(),0)
 allowed=false;await page.reload();await page.getByRole('link',{name:'http://10.10.10.26',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Настроить с телефона',exact:true}).count(),0)
 assert.deepEqual(errors,[]);console.log('Onboarding: RU/UZ/EN help, focus/Escape, Owner QR, separate pairing, confirmation and primary restriction passed.')
}finally{await browser?.close();server.kill()}
