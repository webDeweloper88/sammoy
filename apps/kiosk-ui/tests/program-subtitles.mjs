import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5193',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5193','--strictPort'],{stdio:'ignore'});let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});const p=await browser.newPage({viewport:{width:1080,height:1920}});let design='cards',description={uz:'Owner suv tavsifi',ru:'Описание владельца',kz:'Иесінің сипаттамасы',ky:'Ээсинин сүрөттөмөсү'};const posts=[]
 await p.route('**/api/**',async r=>{const path=new URL(r.request().url()).pathname;let data;if(r.request().method()!=='GET')posts.push(path)
 if(path==='/api/wash/state')data={state:{creditSum:11000,phase:'idle',lastIoOk:true,runtimeAgeSeconds:0,pauseState:'none'},parameters:{tariffs:{water:{enabled:true},foam:{enabled:true}}}}
 else if(path==='/api/kiosk/settings')data={config:{theme:{design,appearance:{mode:'manual',manualTheme:'light'}},programs:[{id:'water',visible:true,description},{id:'foam',visible:true}],contacts:{}},station:{postNo:1}}
 else if(path==='/api/kiosk/payment-options')data={click:{enabled:false}};else throw Error(path)
 await r.fulfill({json:data})})
 for(design of ['cards','wheel']){
  await p.goto(origin+'/wash');await p.locator(`.wash-kiosk[data-design=${design}]`).waitFor()
  for(const [lang,name] of [['uz','O‘zbekcha'],['ru','Русский'],['kz','Қазақша'],['ky','Кыргызча']]){
   await p.getByRole('button',{name,exact:true}).click();const nameByLang={uz:'SUV',ru:'ВОДА',kz:'СУ',ky:'СУУ'};const selector=design==='cards'?`.program-card[aria-label="${nameByLang[lang]}"] small`:`.wheel-segment[aria-label="${nameByLang[lang]}"] .segment-description`;await p.waitForFunction(({selector,text})=>document.querySelector(selector)?.textContent===text,{selector,text:description[lang]})
  }
 }
 description={uz:''};await p.reload();await p.locator('.wheel-segment[aria-label="SUV"] .segment-description').first().waitFor({state:'attached'});assert.equal(await p.locator('.wheel-segment[aria-label="SUV"] .segment-description').first().textContent(),'');assert.deepEqual(posts,[]);console.log('PASS Owner subtitles in both designs/four languages, empty subtitle hides text, no commands')
}finally{await browser?.close();server.kill()}
