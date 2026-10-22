import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {mkdir} from 'node:fs/promises'
const origin='http://127.0.0.1:5192'
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5192','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1000,height:1100},hasTouch:true});page.setDefaultTimeout(12000)
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 let cfg={enabled:true,local_post:1,primary_post:1,standby_post:2,generation:3,standby_ready:true,peer_urls:{1:'http://10.10.10.8',2:'http://10.10.10.7',3:'http://10.10.10.33'}}
 let operation=null,plan=null,changed=0,recovered=0,polls=0,fail=false
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname,body=req.method()==='POST'?req.postDataJSON():null
  let data
  if(path==='/api/auth/me')data={login:'owner',role:'owner'}
  else if(path==='/api/auth/login'){assert.equal(body.login,'owner');assert.equal(body.password,'new-owner-password');data={access_token:'fresh',user:{login:'owner',role:'owner'}}}
  else if(path==='/api/wallet-management/status'){
   if(operation?.stage==='checking'&&++polls>1){operation.stage='completed';cfg={...cfg,...plan.after,standby_ready:true}}
   data={ok:true,configuration:cfg,operation}
  }else if(path==='/api/wallet-management/preview'){
   assert.equal(body.kind,'replace_standby');assert([2,3].includes(body.target_post))
   plan={ok:true,before:{primary_post:1,standby_post:2,generation:3},after:{primary_post:1,standby_post:body.target_post,generation:4}}
   data=plan
  }else if(path==='/api/wallet-management/change'){
   assert.equal(req.headers().authorization,'Bearer fresh');assert.deepEqual(body.expected_authority,plan.before)
   changed++;operation={...body,before:plan.before,after:plan.after,stage:fail?'copying':'checking',error:fail?'interrupted':null}
   data={ok:true,operation}
  }else if(path==='/api/wallet-management/resume'){
   assert.equal(body.request_id,operation.request_id);operation.stage='checking';operation.error=null;polls=0;data={ok:true,operation}
  }else if(path==='/api/wallet-management/recover'){
   assert(body.old_primary_fenced&&body.single_copy_accepted);assert.equal(req.headers().authorization,'Bearer fresh')
   recovered++;cfg={...cfg,primary_post:3,standby_post:1,generation:5};data={ok:true,configuration:cfg}
  }else throw Error('Unexpected '+path)
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 await page.goto(origin+'/tests/post-management.html')
 await page.getByRole('heading',{name:'Посты и резервирование',exact:true}).waitFor()
 const shots='/opt/sammoy/artifacts/post-management-review-20261021';await mkdir(shots,{recursive:true})
 await page.screenshot({path:shots+'/owner-ru.png',fullPage:true})
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:shots+'/owner-mobile.png',fullPage:true})
 await page.setViewportSize({width:1000,height:1100});await page.goto(origin+'/tests/post-management.html?lang=uz');await page.getByRole('heading',{name:'Postlar va zaxiralash',exact:true}).waitFor();await page.screenshot({path:shots+'/owner-uz.png',fullPage:true});await page.goto(origin+'/tests/post-management.html')
 await page.getByRole('button',{name:'Заменить резерв',exact:true}).click()
 await page.getByLabel('Номер нового резервного поста',{exact:true}).fill('3')
 await page.getByRole('button',{name:'Проверить и продолжить',exact:true}).click()
 const dialog=page.getByRole('dialog');await dialog.waitFor()
 assert((await dialog.innerText()).includes('резерв — пост 3'))
 assert.equal(changed,0)
 await dialog.getByLabel('Пароль',{exact:true}).fill('new-owner-password')
 await dialog.getByRole('button',{name:'Подтвердить',exact:true}).click()
 await page.getByText('Новые роли подтверждены.',{exact:true}).waitFor();assert.equal(changed,1)
 assert.equal(await page.getByText(/PROMOTE POST/).count(),0)
 // A failed attempt is restored from server state after page reload.
 cfg={...cfg,primary_post:1,standby_post:2,generation:3};operation=null;fail=true;polls=0
 await page.reload();await page.getByRole('button',{name:'Заменить резерв',exact:true}).click()
 await page.getByRole('button',{name:'Проверить и продолжить',exact:true}).click()
 await dialog.getByLabel('Пароль',{exact:true}).fill('new-owner-password');await dialog.getByRole('button',{name:'Подтвердить',exact:true}).click()
 await page.getByRole('button',{name:'Продолжить проверку',exact:true}).waitFor()
 const oldId=operation.request_id;operation.error=null;await page.reload()
 await page.getByRole('button',{name:'Продолжить проверку',exact:true}).click()
 await dialog.getByLabel('Пароль',{exact:true}).fill('new-owner-password');await dialog.getByRole('button',{name:'Подтвердить',exact:true}).click()
 await page.getByText('Новые роли подтверждены.',{exact:true}).waitFor();assert.equal(operation.request_id,oldId);assert.equal(changed,2)
 // A standby sees recovery, with physical fencing and single-copy confirmation.
 cfg={...cfg,local_post:3};await page.reload()
 await page.getByText('Главный пост неисправен?',{exact:true}).click()
 await page.getByRole('button',{name:'Восстановить работу на этом посту',exact:true}).click()
 const next=page.getByRole('button',{name:'Проверить и продолжить',exact:true});assert(await next.isDisabled())
 await page.getByLabel('Прежний главный физически отключён',{exact:true}).check()
 await page.getByLabel('Понимаю: до восстановления резерва данные будут храниться на одном серверном посту',{exact:true}).check()
 await next.click();await dialog.getByLabel('Пароль',{exact:true}).fill('new-owner-password');await dialog.getByRole('button',{name:'Подтвердить',exact:true}).click()
 await page.getByText('Этот пост стал главным. Подключите резерв и проверьте синхронизацию.',{exact:true}).waitFor();assert.equal(recovered,1)
 // First attachment uses the already selected reserve without retyping roles.
 cfg={...cfg,local_post:1,primary_post:1,standby_post:2,generation:3,standby_ready:false,single_node:false};operation=null;fail=false;polls=0;await page.reload();await page.getByRole('button',{name:'Подключить резерв',exact:true}).click();assert.equal(await page.getByLabel('Номер нового резервного поста',{exact:true}).inputValue(),'2');await page.getByRole('button',{name:'Проверить и продолжить',exact:true}).click();await dialog.getByLabel('Пароль',{exact:true}).fill('new-owner-password');await dialog.getByRole('button',{name:'Подтвердить',exact:true}).click();await page.getByText('Новые роли подтверждены.',{exact:true}).waitFor();assert.equal(changed,3);
 assert.deepEqual(errors,[])
 console.log('PASS station management: explicit preview/password, replacement, persisted retry, no command typing, gated emergency recovery')
}finally{await browser?.close();server.kill()}
