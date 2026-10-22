import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5198'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5198','--strictPort'],{stdio:'ignore'})
let browser
try {
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:390,height:844}})
 await page.addInitScript(()=>{sessionStorage.setItem('sammoy-owner-token','fixture');localStorage.setItem('sammoy-ui-language','ru')})
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 let saved
 const report={summary:{},modes:[],timeline:[]}
 const value={tariffs:{aroma_1:{enabled:true,amountSum:1000,durationSeconds:1}},pauseEnabled:true,freePauseSeconds:300,paidPause:{enabled:true,amountSum:250,durationSeconds:1},purge:{enabled:false,idleSeconds:7200,durationSeconds:30}}
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;let data
  if(path==='/api/auth/me')data={role:'owner',login:'owner',must_change_password:false}
  else if(path==='/api/owner/site/overview')data={...report,complete:true,online_posts:1,primary_post:1,manage_allowed:true,checked_at:new Date().toISOString(),posts:[{post_no:2,status:'online',device_type:'dry_fog',state:{lastIoOk:true,creditSum:0},report}]}
  else if(path==='/api/owner/site/posts/2/parameters'){
   if(req.method()==='POST')saved=req.postDataJSON()
   data={post_no:2,confirmed:req.method()==='POST',revision:'a'.repeat(64),value:saved?.value||value}
  }else throw Error('Unexpected API '+path)
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 await page.goto(origin+'/owner/site')
 await page.getByRole('button',{name:'Настройки',exact:true}).click()
 const enabled=page.getByLabel('Включить автопродувку',{exact:true})
 await enabled.waitFor();assert.equal(await enabled.isChecked(),false)
 assert.equal(await page.getByLabel('Интервал простоя, минут',{exact:true}).count(),0)
 await enabled.check()
 const interval=page.getByLabel('Интервал простоя, минут',{exact:true})
 assert.equal(await interval.inputValue(),'120')
 await interval.click()
 await interval.fill('180')
 await page.getByLabel('Длительность продувки, секунд',{exact:true}).click()
 await page.getByLabel('Длительность продувки, секунд',{exact:true}).fill('45')
 await page.locator('.keyboard-done').click()
 await page.getByRole('button',{name:'Сохранить на этом посту',exact:true}).click()
 await page.getByRole('status').filter({hasText:'Пост подтвердил сохранение'}).waitFor()
 assert.deepEqual(saved.value.purge,{enabled:true,idleSeconds:10800,durationSeconds:45})
 await enabled.uncheck()
 await page.getByRole('button',{name:'Сохранить на этом посту',exact:true}).click()
 await page.getByRole('status').filter({hasText:'Пост подтвердил сохранение'}).waitFor()
 assert.equal(saved.value.purge.enabled,false)
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
 assert.deepEqual(errors,[])
 console.log('PASS purge Owner settings: mobile, defaults, minute conversion, duration, enable/disable, target confirmation')
} finally {await browser?.close();server.kill()}
