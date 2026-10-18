import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5196',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5196','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:1920}}),ids=['water','foam','wax','chem','osmos','nano','air','vacuum'];let visible=ids,theme='light',commands=0
 await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;let data
  if(route.request().method()==='POST')commands++
  if(path==='/api/wash/state')data={state:{creditSum:0,lastIoOk:true,runtimeAgeSeconds:0,phase:'no_credit',pauseState:'none',internetOnline:true},parameters:{tariffs:Object.fromEntries(ids.map(id=>[id,{enabled:true}]))}}
  else if(path==='/api/kiosk/settings')data={config:{theme:{design:'cards',appearance:{mode:'manual',manualTheme:theme}},programs:ids.map(id=>({id,visible:visible.includes(id)})),contacts:{}},station:{postNo:1}}
  else if(path==='/api/kiosk/payment-options')data={click:{enabled:false}}
  else throw Error(path)
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 for(theme of ['light','dark'])for(const count of [6,5,4,3,2,1]){
  visible=[...ids.slice(0,6).filter(id=>id!=='foam').slice(0,count),...(count===6?['foam']:[]),'air'];await page.goto(origin+'/wash')
  await page.locator(`.wash-kiosk[data-theme=${theme}]`).waitFor();await page.locator('.wash-topup strong').getByText('Yuvishga tayyormisiz?',{exact:true}).waitFor()
  const cards=page.locator('.program-card');assert.equal(await cards.count(),count);assert.equal(await page.locator('.wash-start-guide,.card-idle-guidance,.card-pause').count(),0)
  const grid=await page.locator('.program-card-grid').boundingBox(),last=await cards.last().boundingBox();assert(Math.abs(last.y+last.height-(grid.y+grid.height))<3)
  if(count%2)assert(Math.abs(last.width-grid.width)<3)
  if(count<6)assert.equal(await page.getByRole('button',{name:'KO‘PIK',exact:true}).count(),0)
  const optional=await page.locator('.wash-optional button').boundingBox(),row=await page.locator('.wash-optional>div').boundingBox();assert(Math.abs(optional.width-row.width)<3)
  assert(await page.evaluate(()=>document.documentElement.scrollHeight===innerHeight&&document.documentElement.scrollWidth===innerWidth))
  if(count===5)await page.screenshot({path:`../../docs/ui-program-layout-five-${theme}.png`})
 }
 assert.equal(commands,0);console.log('PASS 1–6 visible program layouts in both themes: odd final card fills row, no hidden foam gap, optional air fills width, idle payment copy, no overflow/commands')
}finally{await browser?.close();server.kill()}
