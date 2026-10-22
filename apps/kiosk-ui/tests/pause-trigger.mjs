import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5198',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5198','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:1920}}),errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message))
 let theme='light',held=true
 await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;let data
  if(route.request().method()==='POST')posts.push(path)
  if(path==='/api/wash/state')data={state:{creditSum:11000,phase:'pause_free',selectedMode:'pause',armedMode:'water',activeMode:null,pauseState:'free',freePauseRemaining:40,remainingSeconds:40,resumeRequiresTriggerReset:held,totalStopActive:held,lastIoOk:true,runtimeAgeSeconds:0,internetOnline:true},parameters:{paidPause:{enabled:true,amountSum:1000,durationSeconds:120},tariffs:{water:{enabled:true}}}}
  else if(path==='/api/kiosk/settings')data={config:{theme:{design:'cards',appearance:{mode:'manual',manualTheme:theme}},programs:[{id:'water',visible:true}],contacts:{}},station:{postNo:1}}
  else if(path==='/api/kiosk/payment-options')data={click:{enabled:false}}
  else throw Error(path)
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 for(theme of ['light','dark']){
  held=true;await page.route('**/api/commissioning/state',r=>r.fulfill({json:{complete:true}}));await page.goto(origin+'/wash');await page.locator(`.wash-kiosk[data-theme=${theme}]`).waitFor()
  const button=page.locator('.card-pause');await button.getByText('Avval pistolet tepkisini qo‘yib yuboring',{exact:true}).waitFor();assert(await button.isDisabled())
  const style=await button.evaluate(el=>({opacity:getComputedStyle(el).opacity,color:getComputedStyle(el).color,background:getComputedStyle(el).backgroundColor,small:getComputedStyle(el.querySelector('small')).color}))
  assert.equal(style.opacity,'1');assert.equal(style.small,style.color);assert.equal(style.color,theme==='light'?'rgb(41, 70, 93)':'rgb(212, 226, 238)')
  await page.screenshot({path:`../../docs/ui-pause-trigger-${theme}.png`})
  held=false;await button.getByText(/Bepul pauza/).waitFor();assert(await button.isEnabled())
 }
 assert.deepEqual(posts,[]);assert.deepEqual(errors,[]);console.log('PASS held-trigger pause: readable disabled label and release instruction in both themes; resume enabled after release; no commands sent')
}finally{await browser?.close();server.kill()}
