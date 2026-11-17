import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin=process.env.TEST_ORIGIN||'http://127.0.0.1:5196'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','0.0.0.0','--port','5196','--strictPort'],{stdio:'ignore'})
let browser,context
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(resolve=>setTimeout(resolve,100))}}
 browser=process.env.BROWSER_CDP_URL?await chromium.connectOverCDP(process.env.BROWSER_CDP_URL):await chromium.launch({headless:true})
 context=await browser.newContext()
 await context.addInitScript(()=>{sessionStorage.setItem('sammoy-owner-token','fixture');localStorage.setItem('sammoy-ui-language','ru')})
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message))
 let requests=0,approved=0,running=false
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname
  let result={ok:true}
  if(path==='/api/auth/me')result={id:1,login:'owner',role:'owner',display_name:'Owner',auth_method:'nfc_pin'}
  else if(path==='/api/owner/updates')result={ok:true,manage_allowed:true,primary_post:3,posts:[{post_no:3,online:true,ok:true,ready:true,trusted_key_configured:true,agent_protocol:2,installed:{release_no:0,version:'legacy'}}],queue:running?{status:'running',version:'2026.11.17.1',posts:[{post_no:3,status:'waiting'}]}:null}
  else if(path==='/api/owner/updates/check')result={ok:true,release:{manifest:{release_no:3,version:'2026.11.17.1',notes:{ru:'Новая функция NFC'},artifact:{bytes:100}}}}
  else if(path==='/api/owner/updates/start'){
   requests++
   if(!req.headers()['x-owner-confirmation'])return route.fulfill({status:428,json:{detail:'owner_password_required'}})
   assert.equal(req.postDataJSON().password,'fixture-owner-password');approved++;running=true
  }else if(path==='/api/auth/confirm-action'){
   assert.equal(req.postDataJSON().path,'/api/owner/updates/start');result={grant:'fixture-grant'}
  }else throw Error('Unexpected request '+path)
  await route.fulfill({json:result})
 })
 await page.goto(origin+'/owner/updates')
 await page.getByRole('heading',{name:'Доступна версия 2026.11.17.1'}).waitFor()
 assert.equal(requests,0,'Publication must not automatically start installation')
 await page.getByRole('button',{name:'Обновить посты',exact:true}).click()
 await page.locator('.confirm-dialog input').fill('fixture-owner-password')
 assert.equal(requests,0,'Opening the dialog must not start installation')
 await page.getByRole('button',{name:'Начать обновление',exact:true}).click()
 const confirmation=page.locator('.owner-confirmation');await confirmation.waitFor()
 assert.equal(approved,0)
 assert.equal(await confirmation.evaluate(el=>getComputedStyle(el).zIndex),'115')
 await confirmation.locator('input').fill('fixture-owner-password')
 await confirmation.getByRole('button',{name:'Подтвердить',exact:true}).click()
 await page.getByText('2026.11.17.1 — Обновление выполняется',{exact:true}).waitFor()
 assert.equal(approved,1)
 assert.deepEqual(errors,[])
 console.log('Update opt-in and NFC-session password confirmation: passed')
}finally{await context?.close();await browser?.close();server.kill()}
