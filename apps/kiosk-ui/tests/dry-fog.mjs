import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5192',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5192','--strictPort'],{stdio:'ignore'});let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});const page=await browser.newPage({viewport:{width:1080,height:1920},hasTouch:true}),requests=[],errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))requests.push(r.url())})
 await page.goto(origin+'/preview/dry-fog');await page.locator('.dry-fog-design').waitFor();assert.equal(await page.locator('.wash-brand strong').textContent(),'LABRIX DRY FOG')
 for(const theme of ['dark','light']){
  await page.locator('.preview-tools summary').click();await page.getByLabel('Вид',{exact:true}).selectOption(theme);await page.getByLabel('Состояние',{exact:true}).selectOption('balance');await page.locator('.preview-tools summary').click()
  assert.equal(await page.locator('.program-card').count(),5);assert.equal(await page.locator('.wash-optional button').count(),2);await page.waitForFunction(()=>[...document.querySelectorAll('.mode-photo')].every(i=>i.complete&&i.naturalWidth>0))
  const grid=await page.locator('.program-card-grid').boundingBox(),last=await page.locator('.program-card').last().boundingBox();assert(Math.abs(grid.width-last.width)<2)
  for(const name of ['SHEIKH SULTAN','BLACK ICE','NARCOTIC','INVICTUS CREED','ANTI-TOBACCO','SHINA QORAYTIRISH','SHINANI DAMLASH']){
   await page.getByRole('button',{name,exact:true}).click();assert.equal(await page.locator('.card-status-detail strong').textContent(),name);assert.equal(await page.locator('.program-card.running,.wash-optional button.running').count(),1);assert.equal(await page.locator('.status-primary strong').textContent(),'00:25');assert(!(await page.locator('.card-status-detail').innerText()).includes('Pistolet'));assert(!(await page.locator('.card-status-detail').innerText()).includes('Yuvish'))
  }
  await page.getByRole('button',{name:'SHEIKH SULTAN',exact:true}).click();await page.screenshot({path:`../../docs/ui-dry-fog-${theme}-active.png`})
  await page.getByRole('button',{name:'PAUZA',exact:true}).click();await page.locator('.card-pause.pause-free').waitFor();assert.equal(await page.locator('.status-primary strong').textContent(),'05:00');await page.getByRole('button',{name:'DAVOM ETISH',exact:true}).click();assert.equal(await page.locator('.program-card.running').count(),1)
  await page.locator('.preview-tools summary').click();await page.getByLabel('Состояние',{exact:true}).selectOption('paid');await page.locator('.preview-tools summary').click();await page.locator('.card-pause.pause-paid').waitFor();assert((await page.locator('.card-pause small').textContent()).includes('250 so‘m / 1 s'))
  for(const lang of ['Русский','Қазақша','Кыргызча','O‘zbekcha']){await page.getByRole('button',{name:lang,exact:true}).click();assert(await page.locator('.program-cards h2').innerText())}
  await page.locator('.preview-tools summary').click();await page.getByLabel('Состояние',{exact:true}).selectOption('empty');await page.locator('.preview-tools summary').click();await page.screenshot({path:`../../docs/ui-dry-fog-${theme}-empty.png`})
  assert(await page.evaluate(()=>document.documentElement.scrollWidth===innerWidth&&document.documentElement.scrollHeight===innerHeight));assert.equal(await page.getByRole('button',{name:/purge/i}).count(),0)
 }
 assert.deepEqual(requests,[]);assert.deepEqual(errors,[]);console.log('PASS dry fog preview: 5+2 services, seven images, two themes/four languages, 1000/s tariff, 300s free pause, 250/s paid pause; zero API/hardware/payment calls')
}finally{await browser?.close();server.kill()}
