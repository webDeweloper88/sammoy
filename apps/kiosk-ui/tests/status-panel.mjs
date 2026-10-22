import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5197'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5197','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const p=await browser.newPage({viewport:{width:1080,height:1920}}),errors=[],posts=[]
 p.on('pageerror',e=>errors.push(e.message))
 const ids=['water','foam','wax','chem','osmos','nano','air','vacuum']
 let theme='dark',s
 const base={creditSum:25000,phase:'active',activeMode:'foam',selectedMode:'foam',armedMode:'foam',lastIoOk:true,runtimeAgeSeconds:0,pauseState:'none',remainingSeconds:500,displayTimeKind:'program'}
 await p.route('**/api/**',async r=>{
  if(r.request().method()!=='GET')posts.push(r.request().url())
  const path=new URL(r.request().url()).pathname
  const data=path==='/api/wash/state'?{ok:true,state:s,parameters:{paidPause:{enabled:true,amountSum:1000,durationSeconds:120},tariffs:Object.fromEntries(ids.map(id=>[id,{enabled:true}]))}}:path==='/api/kiosk/settings'?{ok:true,config:{programs:ids.map(id=>({id,visible:true})),theme:{design:'cards',appearance:{mode:'manual',manualTheme:theme}}}}:{ok:true,click:{enabled:false}}
  await r.fulfill({json:data})
 })
 for(theme of ['dark','light']){
  s={...base};await p.route('**/api/commissioning/state',r=>r.fulfill({json:{complete:true}}));await p.goto(origin+'/wash');const panel=p.locator('.card-status-detail');await panel.locator('.card-status-dot').waitFor()
  assert.equal(await panel.evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)')
  await panel.getByText('Ishlamoqda',{exact:true}).waitFor();assert((await p.locator('.status-scene').getAttribute('src')).endsWith('/foam.webp'));await p.waitForFunction(()=>document.querySelector('.status-scene')?.naturalWidth===1600);await p.screenshot({path:`../../docs/ui-status-scene-${theme}-active.png`})
  s={...base,phase:'trigger_wait',activeMode:null};await p.locator('.card-status-detail.state-waiting').waitFor();assert.equal(await panel.locator('.card-status-dot').count(),0);await panel.getByText('Pistolet tepkisini bosing',{exact:true}).waitFor()
  for(const pause of ['free','paid']){
   s={...base,phase:'pause_'+pause,activeMode:null,selectedMode:'pause',pauseState:pause,remainingSeconds:pause==='free'?41:120,displayTimeKind:pause+'_pause'}
   await p.locator('.card-status-detail.state-'+pause).waitFor();assert.equal(await panel.locator('svg[data-icon=pause]').count(),1)
   if(pause==='paid')assert.match(await panel.locator('.card-status-note').textContent(),/1\s000 so‘m \/ 120 s/)
   await p.screenshot({path:`../../docs/ui-status-${theme}-${pause}.png`})
  }
  s={...base,lastRfidResult:'card_in_use',lastRfidProcessedAt:new Date().toISOString()};await panel.getByText(/Karta boshqa postga/).waitFor()
  s={...base,lastRfidResult:'wallet_error',walletLastError:'VIP daily limit reached',lastRfidProcessedAt:new Date().toISOString()};await panel.getByText(/Bugungi VIP limiti tugadi/).waitFor();assert(!await panel.textContent().then(t=>t.includes('vaqtincha')));
  s={...base,creditSum:0,phase:'no_credit',activeMode:null,armedMode:null,selectedMode:'pause',remainingSeconds:null};await p.locator('.card-idle-guidance').waitFor();assert.equal(await p.locator('.card-pause').count(),0);await panel.getByText('Yuvishni boshlash',{exact:true}).waitFor();assert((await p.locator('.status-scene').getAttribute('src')).endsWith('/nano.webp'));await p.screenshot({path:`../../docs/ui-audit-${theme}-empty.png`});
  s={...base,lastIoOk:false};await p.locator('.card-status-detail.state-fault').waitFor();await panel.getByText(/Uskuna tayyor emas/).waitFor();assert.equal(await panel.locator('strong').count(),0)
 }
 assert.deepEqual(posts,[]);assert.deepEqual(errors,[])
 console.log('PASS unified panel: transparent surface, active/waiting, free/paid pause rate, card conflicts and hardware fault in both themes; no commands')
}finally{await browser?.close();server.kill()}
