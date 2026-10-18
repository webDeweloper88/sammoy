import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5190'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5190','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:1920},hasTouch:true})
 let s={phase:'no_credit',creditSum:0,selectedMode:'pause',armedMode:null,activeMode:null,requestedOutput:null,lastIoOk:true,runtimeAgeSeconds:0,activeSessionId:null,lastError:null,licenseLocked:false,pauseState:'none'}
 let posts=0
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname
  if(route.request().method()==='POST')posts++
  const ids=['water','foam','wax','osmos','nano','chem']
  const data=path==='/api/wash/state'?{ok:true,state:s,parameters:{tariffs:Object.fromEntries(ids.map(id=>[id,{enabled:true}]))}}:path==='/api/kiosk/settings'?{ok:true,config:{programs:ids.map(id=>({id,visible:true}))}}:{ok:true,click:{enabled:false}}
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 await page.clock.install()
 await page.goto(origin+'/')
 await page.getByRole('button',{name:'SUV',exact:true}).waitFor()
 await page.clock.runFor(179000)
 assert.equal(await page.locator('.idle-screen').count(),0)
 await page.clock.runFor(2000)
 await page.locator('.idle-screen').waitFor()
 await page.getByRole('button',{name:'Русский',exact:true}).tap()
 assert.equal(await page.locator('.idle-screen').count(),1)
 await page.touchscreen.tap(500,900)
 await page.locator('.wash-screen').waitFor()
 assert.equal(posts,0)
 await page.getByRole('button',{name:'O‘zbekcha',exact:true}).tap()
 await page.clock.runFor(181000)
 await page.locator('.idle-screen').waitFor()
 s={...s,creditSum:1000,activeSessionId:7,phase:'idle'}
 await page.clock.runFor(1000)
 await page.locator('.wash-screen').waitFor()
 assert.equal(posts,0)
 await page.clock.runFor(181000)
 assert.equal(await page.locator('.idle-screen').count(),0)
 s={...s,runtimeAgeSeconds:10}
 await page.clock.runFor(1000)
 assert.equal(await page.getByRole('button',{name:'SUV',exact:true}).getAttribute('aria-disabled'),'true')
 console.log('PASS Idle integration: 3 minutes, language exception, wake without command, incoming credit, funded-session and frozen-runtime guards')
}finally{await browser?.close();server.kill()}
