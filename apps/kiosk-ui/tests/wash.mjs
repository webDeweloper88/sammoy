import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5189'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5189','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:1920},hasTouch:true})
 let s={phase:'idle',creditSum:25000,selectedMode:'pause',activeMode:null,armedMode:null,requestedOutput:null,lastIoOk:true,runtimeAgeSeconds:0,lastError:null,licenseLocked:false,pauseState:'none',remainingSeconds:null,displayTimeKind:'unselected',activeSessionId:1,freePauseRemaining:60,lastRfidStatus:'online',internetOnline:true,billPulses:0}
 const names=['water','foam','wax','osmos','nano','chem','air','vacuum']
 let config={programs:names.map(id=>({id,visible:true})),payment:{minAmount:1000,maxAmount:100000,quickAmounts:[5000,10000,20000]}}
 const parameters={tariffs:Object.fromEntries(names.map(id=>[id,{enabled:true,amountSum:1000,durationSeconds:20}]))}
 let posts=[],errors=[],intent=null,paymentStatus='pending',offline=false
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname,method=route.request().method()
  if(method==='POST')posts.push([path,route.request().postDataJSON()])
  let data
  if(path==='/api/wash/state'){if(offline){await route.abort();return}data={ok:true,state:s,parameters}}
  else if(path==='/api/kiosk/settings')data={ok:true,config}
  else if(path==='/api/kiosk/payment-options')data={ok:true,click:{enabled:true,minAmount:1000,maxAmount:100000}}
  else if(path==='/api/wash/mode'){
   const mode=route.request().postDataJSON().mode
   if(mode==='pause')s={...s,selectedMode:'pause',activeMode:null,requestedOutput:null,phase:'pause_free',pauseState:'free',remainingSeconds:41,displayTimeKind:'free_pause',resumeRequiresTriggerReset:true}
   else s={...s,selectedMode:mode,armedMode:mode,activeMode:mode,requestedOutput:mode,phase:'active',pauseState:'none',remainingSeconds:500,displayTimeKind:'program'}
   data={ok:true,state:s,parameters}
  }
  else if(path==='/api/click/intents'){
   intent={id:'test-payment',amount_sum:10000,status:'pending',payment_url:'https://example.test/pay/test'};data={ok:true,intent}
  }
  else if(path==='/api/click/intents/test-payment'){intent={...intent,status:paymentStatus};data={ok:true,intent}}
  else if(path==='/api/click/intents/test-payment/cancel'){paymentStatus='cancelled';data={ok:true,intent:{...intent,status:paymentStatus}}}
  else throw Error('Unexpected API '+path)
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 await page.goto(origin+'/wash')
 await page.getByText('25 000',{exact:true}).waitFor()
 await page.getByRole('button',{name:'SUV',exact:true}).waitFor()
 assert.equal(await page.locator('.wheel-segment').count(),6)
 assert.equal(await page.locator('.wash-optional button').count(),2)
 assert(await page.evaluate(()=>document.documentElement.scrollHeight===innerHeight&&document.documentElement.scrollWidth===innerWidth))
 await page.screenshot({path:'../../docs/ui-wash-balance-1080x1920.png'})
 s={...s,creditSum:55000,bonusSum:5000}
 await page.getByText('55 000',{exact:true}).waitFor();await page.locator('.bonus-caption').getByText(/5 000/).waitFor()
 for(const theme of ['light','dark']){
  config={...config,theme:{appearance:{mode:'manual',manualTheme:theme}}}
  await page.locator(`.wash-kiosk[data-theme=${theme}]`).waitFor()
  assert(await page.evaluate(()=>document.documentElement.scrollHeight===innerHeight))
  const bounds=await page.locator('.bonus-caption').evaluate(e=>{const b=e.getBoundingClientRect(),p=e.closest('.wash-status').getBoundingClientRect();return b.bottom<=p.bottom&&b.left>=p.left&&b.right<=p.right});assert(bounds)
  await page.screenshot({path:`../../docs/ui-bonus-${theme}-1080x1920.png`})
 }
 s={...s,creditSum:25000,bonusSum:0}
 await page.locator('.bonus-caption').waitFor({state:'hidden'})

 // A first tap asks the customer to wait, not to tap again while busy.
 s={...s,walletTransferPending:true,walletOperationInProgress:true}
 await page.getByText('Karta bilan operatsiya bajarilmoqda. Iltimos, kuting…',{exact:true}).waitFor()
 assert.equal(await page.getByText(/Kartani qayta yaqinlashtiring/).count(),0)
 assert.equal(await page.getByRole('button',{name:'SUV',exact:true}).getAttribute('aria-disabled'),'true')
 // A durable interrupted operation requests the same card again.
 s={...s,walletOperationInProgress:false,walletLastError:'network interrupted'}
 await page.getByText(/Kartani qayta yaqinlashtiring/).waitFor()
 s={...s,walletTransferPending:false,walletLastError:null}
 await page.getByText(/Kartani qayta yaqinlashtiring/).waitFor({state:'hidden'})

 await page.getByRole('button',{name:'KO‘PIK',exact:true}).tap()
 await page.locator('.wash-status.time-primary').waitFor()
 assert.deepEqual(posts.at(-1),['/api/wash/mode',{mode:'foam'}])
 await page.screenshot({path:'../../docs/ui-wash-active-1080x1920.png'})
 await page.getByRole('button',{name:'PAUZA',exact:true}).tap()
 assert.deepEqual(posts.at(-1),['/api/wash/mode',{mode:'pause'}])
 await page.getByRole('button',{name:'DAVOM ETISH',exact:true}).waitFor()
 assert.equal(await page.getByRole('button',{name:'DAVOM ETISH',exact:true}).getAttribute('aria-disabled'),'true')
 await page.waitForFunction(()=>/Avval.*pistolet.*tepkisini/.test(document.querySelector('.wheel-center').textContent))
 s={...s,resumeRequiresTriggerReset:false}
 await page.waitForFunction(()=>document.querySelector('.wheel-center').getAttribute('aria-disabled')==='false')
 await page.getByRole('button',{name:'DAVOM ETISH',exact:true}).tap()
 assert.deepEqual(posts.at(-1),['/api/wash/mode',{mode:'foam'}])
 for(const [label] of [['Қазақша'],['Кыргызча'],['Русский'],['O‘zbekcha']]){await page.getByRole('button',{name:label,exact:true}).tap();assert(await page.evaluate(()=>document.documentElement.scrollWidth===innerWidth))}
 // Visibility comes from configuration, not placeholders.
 config.programs.find(p=>p.id==='air').visible=false
 await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.wash-optional button').length===1)
 config.programs.find(p=>p.id==='vacuum').visible=false
 await page.reload();await page.locator('.without-optional').waitFor()
 assert.equal(await page.locator('.wash-optional').count(),0)
 s={...s,lastIoOk:false,lastError:'fixture failure',phase:'error'}
 await page.getByText(/Uskuna tayyor emas/).waitFor()
 assert.equal(await page.getByRole('button',{name:'SUV',exact:true}).getAttribute('aria-disabled'),'true')
 assert.equal(await page.getByRole('button',{name:'PAUZA',exact:true}).getAttribute('aria-disabled'),'false')
 s={...s,lastIoOk:true,runtimeAgeSeconds:0,lastError:null,phase:'active'}
 await page.getByText('Yuvish davom etmoqda').waitFor()
 await page.locator('.wash-topup').tap()
 await page.screenshot({path:'../../docs/ui-payment-methods-1080x1920.png'})
 await page.getByRole('button',{name:'Naqd pul',exact:true}).tap()
 await page.getByText(/Kupyurani qabul/).waitFor()
 const beforeCash=posts.length
 s={...s,billPulses:1,creditSum:30000}
 await page.locator('.payment-dialog').waitFor({state:'hidden'})
 assert.equal(posts.length,beforeCash)
 await page.locator('.wash-topup').tap()
 await page.getByRole('button',{name:'QR to‘lov',exact:true}).tap()
 await page.getByRole('button',{name:'QR yaratish',exact:true}).tap()
 await page.locator('.payment-qr').waitFor()
 assert.equal(posts.filter(([p])=>p==='/api/click/intents').length,1)
 await page.screenshot({path:'../../docs/ui-wash-qr-1080x1920.png'})
 // Closing/reopening preserves the same intent rather than charging again.
 await page.getByRole('button',{name:'Yopish',exact:true}).first().tap()
 await page.locator('.wash-topup').tap();await page.locator('.payment-qr').waitFor()
 assert.equal(posts.filter(([p])=>p==='/api/click/intents').length,1)
 paymentStatus='prepared';await page.waitForFunction(()=>document.querySelector('.payment-dialog .sheet-action')?.disabled===true)
 assert.equal(await page.getByText('To‘lov balansga tushdi',{exact:true}).count(),0)
 paymentStatus='credited';await page.getByText('To‘lov balansga tushdi').waitFor()
 await page.locator('.payment-dialog').waitFor({state:'hidden'})
 offline=true;await page.getByText(/Ulanish yo‘q/).waitFor()
 assert.equal(await page.getByRole('button',{name:'SUV',exact:true}).getAttribute('aria-disabled'),'true')
 offline=false;s={...s,lastIoOk:true,lastError:null,phase:'active'}
 await page.getByText('Yuvish davom etmoqda').waitFor()
 await page.locator('.wash-topup').tap()
 await page.getByRole('button',{name:'QR to‘lov',exact:true}).tap()
 await page.route('**/api/click/intents',async route=>{posts.push(['/api/click/intents',route.request().postDataJSON()]);await route.abort()})
 await page.getByRole('button',{name:'QR yaratish',exact:true}).tap()
 await page.getByText(/Holat noma’lum/).waitFor()
 const created=posts.filter(([p])=>p==='/api/click/intents').length
 await page.reload()
 await page.locator('.wash-topup').tap()
 await page.getByText(/Holat noma’lum/).waitFor()
 assert.equal(await page.getByRole('button',{name:'QR yaratish',exact:true}).count(),0)
 assert.equal(posts.filter(([p])=>p==='/api/click/intents').length,created)
 assert(!posts.some(([p])=>p.includes('/stop')||p.includes('/credit')))
 assert.deepEqual(errors,[])
 console.log('PASS Screen 2: real API wiring, pause interlock, optional visibility, languages, QR lifecycle, stale-state guards')
}finally{await browser?.close();server.kill()}
