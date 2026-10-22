import { chromium } from 'playwright'
import { spawn } from 'node:child_process'
import assert from 'node:assert/strict'
import {resolveAppearance} from '../src/kiosk/appearance.js'
const auto={mode:'auto',lightStart:'08:00',lightEnd:'18:00'}
for(const [iso,result] of [['2026-10-06T02:59:00Z','dark'],['2026-10-06T03:00:00Z','light'],['2026-10-06T12:59:00Z','light'],['2026-10-06T13:00:00Z','dark']])assert.equal(resolveAppearance(auto,new Date(iso)),result)
assert.equal(resolveAppearance({mode:'manual',manualTheme:'light'},new Date('2026-10-06T23:00:00Z')),'light')
assert.equal(resolveAppearance({mode:'manual',manualTheme:'dark'},new Date('2026-10-06T10:00:00Z')),'dark')
assert.equal(resolveAppearance({...auto,lightStart:'22:00',lightEnd:'06:00'},new Date('2026-10-06T18:00:00Z')),'light')
assert.equal(resolveAppearance({...auto,lightEnd:'08:00'}),'dark')
const origin='http://127.0.0.1:5191'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5191','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const context=await browser.newContext({viewport:{width:1080,height:1920},hasTouch:true,timezoneId:'Europe/London'})
 const page=await context.newPage();const names=['water','foam','wax','osmos','nano','chem','air','vacuum']
 let appearance={mode:'manual',manualTheme:'light',lightStart:'08:00',lightEnd:'18:00'},posts=[],config={theme:{appearance},programs:names.map(id=>({id,visible:true})),payment:{minAmount:1000,maxAmount:100000,quickAmounts:[5000]}}
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname
  if(route.request().method()==='POST')posts.push(path)
  const data=path==='/api/wash/state'?{ok:true,state:{phase:'idle',creditSum:25000,selectedMode:'pause',pauseState:'none',lastIoOk:true,runtimeAgeSeconds:0,lastRfidStatus:'online',internetOnline:true},parameters:{tariffs:Object.fromEntries(names.map(id=>[id,{enabled:true}]))}}:path==='/api/kiosk/settings'?{ok:true,config}:{ok:true,click:{enabled:true,minAmount:1000,maxAmount:100000}}
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 await page.route('**/api/commissioning/state',r=>r.fulfill({json:{complete:true}}));await page.goto(origin+'/wash');await page.locator('.wash-kiosk[data-theme=light]').waitFor()
 assert(await page.evaluate(()=>document.documentElement.scrollHeight===innerHeight&&document.documentElement.scrollWidth===innerWidth))
 await page.screenshot({path:'../../docs/ui-wash-light-1080x1920.png'})
 await page.locator('.wash-topup').tap();await page.locator('.payment-dialog[open]').waitFor()
 assert.equal(await page.locator('.payment-dialog').evaluate(e=>getComputedStyle(e).color),'rgb(11, 35, 56)')
 await page.screenshot({path:'../../docs/ui-payment-light-1080x1920.png'})
 await page.getByRole('button',{name:'Yopish',exact:true}).first().tap()
 appearance.manualTheme='dark'
 await page.locator('.wash-kiosk[data-theme=dark]').waitFor({timeout:20000})
 assert.deepEqual(posts,[])
 await page.clock.install({time:new Date('2026-10-06T02:59:00Z')})
 Object.assign(appearance,auto)
 await page.reload();await page.locator('.wash-kiosk[data-theme=dark]').waitFor()
 await page.clock.runFor(61000);await page.locator('.wash-kiosk[data-theme=light]').waitFor()
 assert.deepEqual(posts,[])
 console.log('PASS themes: manual persistence, live config switch, Tashkent boundaries, cross-midnight, portrait and payment palette, automatic switch without commands')
}finally{await browser?.close();server.kill()}
