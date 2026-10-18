import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5197',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5197','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:1920}});let theme='dark',commands=0,selected='water',resume
 const state=()=>({state:{creditSum:11000,selectedMode:selected,armedMode:selected,activeMode:selected,lastIoOk:true,runtimeAgeSeconds:0,phase:'active',pauseState:'none',internetOnline:true},parameters:{tariffs:{water:{enabled:true},foam:{enabled:true}}}})
 await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;let data
  if(path==='/api/wash/mode'){commands++;await new Promise(r=>resume=r);selected=route.request().postDataJSON().mode;data=state()}
  else if(path==='/api/wash/state')data=state()
  else if(path==='/api/kiosk/settings')data={config:{theme:{design:'cards',appearance:{mode:'manual',manualTheme:theme}},programs:['water','foam'].map(id=>({id,visible:true})),contacts:{}},station:{postNo:1}}
  else if(path==='/api/kiosk/payment-options')data={click:{enabled:false}}
  else throw Error(path)
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 for(theme of ['dark','light']){
  selected='water';commands=0;await page.goto(origin+'/wash');await page.locator(`.wash-kiosk[data-theme=${theme}]`).waitFor()
  const buttons=page.locator('.program-card'),before=await buttons.evaluateAll(els=>els.map(el=>({opacity:getComputedStyle(el).opacity,background:getComputedStyle(el).backgroundColor})))
  await buttons.nth(1).click();await page.locator('.wash-screen[aria-busy=true]').waitFor()
  assert.deepEqual(await buttons.evaluateAll(els=>els.map(el=>({opacity:getComputedStyle(el).opacity,background:getComputedStyle(el).backgroundColor}))),before)
  await buttons.nth(0).click();assert.equal(commands,1);resume();await page.locator('.wash-screen[aria-busy=false]').waitFor();assert.equal(await buttons.nth(1).getAttribute('aria-pressed'),'true')
 }
 console.log('PASS mode switch: no global button dimming during delayed response, duplicate starts ignored, selected state confirmed by server in both themes')
}finally{await browser?.close();server.kill()}
