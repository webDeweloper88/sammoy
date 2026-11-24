import {chromium} from 'playwright'
import {spawn} from 'node:child_process'
import assert from 'node:assert/strict'
const origin='http://127.0.0.1:5196',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5196','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:1920}});page.setDefaultTimeout(12000)
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 let creates=0,status='pending',uploads=0
 await page.route('**/__licensing?*',r=>r.fulfill({contentType:'text/html',body:'<div id="app"></div><script type="module" src="/tests/licensing-fixture.js"></script>'}))
 await page.route('**/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;let data={ok:true}
  const intent={id:'fixture-payment',amount_sum:10000,status,payment_url:'https://example.test/fixture'}
  if(path==='/api/click/intents'){creates++;data={ok:true,intent}}
  else if(path==='/api/click/intents/fixture-payment')data={ok:true,intent}
  else if(path==='/api/admin/install/status')data={license_settings:{site_code:'fixture'},hardware:{},license:{enabled:true,locked:false,state:'grace',license_duration_type:'permanent',authorization_mode:'local_signed',last_error:'Gateway unavailable'}}
  else if(path==='/api/admin/license/authorization-file'){uploads++;assert.match(request.headers()['content-type'],/^multipart\/form-data;/);assert.equal(request.headers().authorization,'Bearer fixture-admin')}
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 await page.goto(origin+'/__licensing?kind=payment');await page.waitForFunction(()=>window.openPayment);await page.evaluate(()=>window.openPayment())
 await page.locator('.payment-method-cash').waitFor();await page.evaluate(()=>window.fixtureState({internetOnline:false}))
 await page.getByText('Click временно недоступен',{exact:true}).waitFor();assert(await page.locator('.payment-method-qr').isDisabled());assert(await page.locator('.payment-method-cash').isEnabled());assert(await page.locator('.payment-method-card').isEnabled())
 await page.evaluate(()=>window.fixtureState({internetOnline:true}));await page.locator('.payment-method-qr').click();await page.locator('.primary-action').click();await page.locator('.payment-qr').waitFor();assert.equal(creates,1)
 await page.evaluate(()=>window.fixtureState({internetOnline:false}));await page.locator('.payment-qr').waitFor({state:'hidden'});await page.getByText(/Click временно недоступен/).waitFor();assert.equal(creates,1)
 await page.evaluate(()=>window.fixtureState({internetOnline:true}));await page.locator('.payment-qr').waitFor();status='credited';await page.getByText('Оплата зачислена',{exact:true}).waitFor();assert.equal(creates,1)
 await page.goto(origin+'/__licensing?kind=admin');await page.getByText(/Подписанная бессрочная лицензия/).waitFor();assert.equal(await page.getByText('Рекомендуемая синхронизация до',{exact:true}).count(),0)
 await page.getByLabel('Файл лицензии JSON',{exact:true}).setInputFiles({name:'license.json',mimeType:'application/json',buffer:Buffer.from('{"schema":"labrix.license-file.v1"}')})
 await page.getByRole('button',{name:'Применить файл',exact:true}).click();await page.getByRole('alertdialog').waitFor();assert.equal(uploads,0);await page.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByText('Запрос выполнен',{exact:true}).waitFor();assert.equal(uploads,1)
 assert.deepEqual(errors,[]);console.log('PASS: Click outage blocks only new QR, preserves pending payment and cash/cards, recovers without a second invoice; Admin shows local licence and imports a signed file with confirmation.')
}finally{await browser?.close();server.kill()}
