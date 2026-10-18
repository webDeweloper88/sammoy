import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5199',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5199','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const p=await browser.newPage({viewport:{width:1080,height:1920}}),errors=[],posts=[];p.on('pageerror',e=>errors.push(e.message))
 const ids=['water','foam','wax','chem','osmos','nano','air','vacuum'];let theme='dark',callId='',delivery='sent'
 await p.route('**/api/**',async r=>{const path=new URL(r.request().url()).pathname;let data
  if(r.request().method()==='POST')posts.push(path)
  if(path==='/api/wash/state')data={ok:true,state:{creditSum:15000,activeSessionSource:'vip',phase:'idle',lastIoOk:true,runtimeAgeSeconds:0,pauseState:'none',lastRfidStatus:'online',internetOnline:true},parameters:{tariffs:Object.fromEntries(ids.map(id=>[id,{enabled:true}]))}}
  else if(path==='/api/kiosk/settings')data={ok:true,station:{postNo:1},config:{programs:ids.map(id=>({id,visible:true})),theme:{design:'cards',appearance:{mode:'manual',manualTheme:theme}},contacts:{operator:{enabled:true,phone:'+998 90 123 45 67'},manufacturer:{marketing:'+998 91 111 69 29',programmer:'+998 91 667 62 28',electrician:'+998 94 584 13 01',telegram:'https://t.me/labrixwash',instagram:'https://www.instagram.com/labrixwash/',youtube:'https://www.youtube.com/@labrixwash'}}}}
  else if(path==='/api/kiosk/payment-options')data={ok:true,click:{enabled:true}}
  else if(path==='/api/kiosk/operator/call'){callId=r.request().postDataJSON().request_id;assert.match(callId,/^[0-9a-f-]{36}$/);data={ok:true,request_id:callId,status:'queued',retry_after:120}}
  else if(path==='/api/kiosk/operator/call/'+callId)data={ok:true,request_id:callId,status:delivery,retry_after:115}
  else throw Error('Unexpected API '+path)
  await r.fulfill({json:data})
 })
 await p.goto(origin+'/wash');await p.getByRole('button',{name:'Operatorni chaqirish',exact:true}).waitFor()
 await p.getByRole('button',{name:'Operatorni chaqirish',exact:true}).click();await p.getByRole('dialog').getByText('Operatorga xabar yuborildi',{exact:true}).waitFor();await p.getByRole('dialog').getByRole('button',{name:'Yopish',exact:true}).first().click()
 await p.getByRole('button',{name:'Operatorni chaqirish',exact:true}).click();await p.getByRole('dialog').getByText('Operatorga xabar yuborildi',{exact:true}).waitFor();assert.equal(posts.length,1);await p.getByRole('dialog').getByRole('button',{name:'Yopish',exact:true}).first().click()
 for(theme of ['dark','light']){
  await p.locator(`.wash-kiosk[data-theme=${theme}]`).waitFor();
  for(const label of await p.locator('.footer-social-links button span,.footer-social-links button svg').all())assert.equal(await label.evaluate(el=>getComputedStyle(el).color),'rgb(255, 255, 255)');
  await p.getByRole('button',{name:'Kontaktlar va servis',exact:true}).click()
  assert.equal(await p.locator('.manufacturer-qr-grid section').count(),3)
  for(const qr of await p.locator('.manufacturer-qr-grid svg').all()){const box=await qr.boundingBox();assert(box.width>=210&&box.height>=210,'Manufacturer QR must remain large enough to scan')}
  for(const phone of ['+998 91 111 69 29','+998 91 667 62 28','+998 94 584 13 01'])await p.getByRole('dialog').getByText(phone,{exact:true}).waitFor()
  await p.screenshot({path:`../../docs/ui-manufacturer-${theme}.png`});await p.getByRole('dialog').getByRole('button',{name:'Yopish',exact:true}).first().click();assert(await p.evaluate(()=>document.documentElement.scrollWidth===innerWidth&&document.documentElement.scrollHeight===innerHeight))
 }
 await p.locator('.wash-topup').click();await p.getByText('To‘lov qilish uchun VIP seansini yakunlang',{exact:true}).waitFor();assert.equal(await p.getByText('VIP seansida mavjud emas',{exact:true}).count(),2)
 assert(await p.getByRole('button',{name:'QR to‘lov',exact:true}).isDisabled());assert(posts.every(x=>x==='/api/kiosk/operator/call'));assert.deepEqual(errors,[])
 console.log('PASS operator UI: one call through repeat taps, sent acknowledgement, all three service phones/QRs, both themes, VIP reason; no wash/payment commands')
}finally{await browser?.close();server.kill()}
