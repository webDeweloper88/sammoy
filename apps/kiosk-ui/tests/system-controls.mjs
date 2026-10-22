import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
const origin='http://127.0.0.1:5199'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5199','--strictPort'],{stdio:'ignore'})
let browser
try {
  for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
  browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
  const page=await browser.newPage({viewport:{width:390,height:844}}), actions=[], errors=[]; let statusPolls=0
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/system-controls-harness',route=>route.fulfill({contentType:'text/html',body:`<html><head><link rel="stylesheet" href="/src/owner.css"></head><body><div id="app"></div><script type="module">import {createApp} from '/node_modules/.vite/deps/vue.js';import Controls from '/src/SystemControls.vue';createApp(Controls,{resets:true,language:'ru',initialLogin:'admin'}).mount('#app')</script></body></html>`}))
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname
    if(path==='/api/auth/login')return route.fulfill({contentType:'application/json',body:JSON.stringify({access_token:'fresh-only',user:{role:'admin'}})})
    if(path==='/api/system/actions'){
      assert.equal(route.request().headers().authorization,'Bearer fresh-only')
      actions.push(route.request().postDataJSON())
      return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,status:'accepted',request_id:actions.at(-1).request_id})})
    }
    if(path.startsWith('/api/system/actions/')){
      assert.equal(route.request().headers().authorization,undefined)
      statusPolls++
      if(statusPolls<3)return route.fulfill({status:502,contentType:'application/json',body:'{}'})
      return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,status:'completed'})})
    }
    throw Error('Unexpected '+path)
  })
  await page.route('**/install',route=>route.fulfill({contentType:'text/html',body:'<h1>Installation wizard</h1>'}))
  await page.goto(origin+'/system-controls-harness')
  await page.getByRole('button',{name:'Полный сброс',exact:true}).click()
  let dialog=page.getByRole('dialog')
  await dialog.getByText('Будут удалены деньги',{exact:false}).waitFor()
  assert(await dialog.getByRole('button',{name:'Подтвердить',exact:true}).isDisabled())
  await dialog.getByLabel('Пароль',{exact:true}).fill('not-real-password')
  await dialog.getByRole('textbox').last().fill('FULL')
  assert(await dialog.getByRole('button',{name:'Подтвердить',exact:true}).isDisabled())
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button',{name:'Подтвердить',exact:true}).click()
  await dialog.getByRole('link',{name:'Открыть установку'}).waitFor()
  assert.equal(actions.length,1);assert.equal(actions[0].action,'full');assert.equal(actions[0].cluster_isolated,true)
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('sammoy-owner-token')),null)
  assert(await dialog.evaluate(el=>el.getBoundingClientRect().width<=innerWidth))
  assert(statusPolls>=3)
  await page.waitForURL(origin+'/install')
  await page.getByRole('heading',{name:'Installation wizard'}).waitFor()
  await page.goto(origin+'/system-controls-harness')
  await page.getByRole('button',{name:'Перезапустить',exact:false}).click()
  dialog=page.getByRole('dialog')
  await dialog.getByLabel('Пароль',{exact:true}).fill('not-real-password')
  await dialog.getByRole('textbox').last().fill('REBOOT')
  await dialog.getByRole('button',{name:'Подтвердить',exact:true}).click()
  await dialog.getByText('Ожидаем завершения операции.',{exact:false}).waitFor()
  assert.equal(actions[1].action,'reboot');assert.deepEqual(errors,[])
  console.log('System controls: destructive warning, isolation, fresh login, local action, mobile width passed')
} finally {if(browser)await browser.close();server.kill()}
