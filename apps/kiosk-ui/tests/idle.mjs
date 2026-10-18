import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { canAttract, IDLE_TIMEOUT_MS } from '../src/kiosk/idle-policy.js'
const now = Date.now()
const valid = { creditSum:0, phase:'idle', lastIoOk:true,runtimeAgeSeconds:0 }
assert.equal(IDLE_TIMEOUT_MS, 180000)
assert(canAttract(valid,{receivedAt:now,now}))
for(const change of [{creditSum:100},{activeSessionId:1},{armedMode:'water'},{lastError:'offline'},{licenseLocked:true},{lastIoOk:false},{powerRecoveryAvailable:true}]) assert(!canAttract({...valid,...change},{receivedAt:now,now}))
assert(!canAttract(null,{receivedAt:now,now}))
assert(!canAttract(valid,{receivedAt:now-6000,now}))
assert(!canAttract(valid,{receivedAt:now,now,paymentPending:true}))
const origin='http://127.0.0.1:5188'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5188','--strictPort'],{stdio:'ignore'})
let browser
try {
  for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
  browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
  const page=await browser.newPage({viewport:{width:1080,height:1920},hasTouch:true})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto(origin+'/preview/idle')
  await page.getByText('BOSHLASH UCHUN EKRANGA TEGING').waitFor()
  assert(await page.evaluate(()=>document.documentElement.scrollWidth===innerWidth && document.documentElement.scrollHeight===innerHeight))
  for(const [name,text] of [['Русский','КОСНИТЕСЬ ЭКРАНА'],['Қазақша','ЭКРАНДЫ ТҮРТІҢІЗ'],['Кыргызча','ЭКРАНГА ТИЙИҢИЗ'],['O‘zbekcha','BOSHLASH UCHUN EKRANGA TEGING']]) {
    await page.getByRole('button',{name,exact:true}).tap()
    await page.getByText(text).waitFor()
  }
  await page.screenshot({path:'../../docs/ui-idle-layout-1080x1920.png'})
  const cta = await page.locator('.idle-cta').boundingBox()
  await page.touchscreen.tap(cta.x + cta.width / 2, cta.y + cta.height / 2)
  await page.getByText('Заставка закрыта',{exact:true}).waitFor()
  await page.getByRole('button',{name:'Вернуться к заставке'}).tap()
  await page.locator('.idle-hero').tap()
  await page.getByText('Заставка закрыта',{exact:true}).waitFor()
  await page.route('**/branding/labrixwash_idle_portrait.webp', route => route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920"><rect width="1080" height="1920" fill="#354550"/></svg>'}))
  await page.goto(origin+'/preview/idle')
  await page.locator('.idle-screen--portrait').waitFor()
  const hero = await page.locator('.idle-hero').boundingBox()
  assert(Math.abs(hero.height-1920)<1)
  assert.equal(hero.width,1080)
  assert.equal(hero.y,0)
  assert(await page.evaluate(()=>document.documentElement.scrollHeight===innerHeight))
  await page.getByRole('button',{name:'Русский',exact:true}).tap()
  await page.getByText('КОСНИТЕСЬ ЭКРАНА').waitFor()
  assert.deepEqual(errors,[])
  console.log('Idle policy and portrait touch preview: PASS')
} finally { await browser?.close();server.kill() }
