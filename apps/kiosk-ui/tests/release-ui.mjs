import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5195',args=['node_modules/vite/bin/vite.js','preview','--host','127.0.0.1','--port','5195','--strictPort'];if(process.env.RELEASE_UI_DIR)args.push('--outDir',process.env.RELEASE_UI_DIR)
const server=spawn(process.execPath,args,{stdio:'ignore'});let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:1920}}),requests=[],errors=[];page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))requests.push(r.url())});page.on('pageerror',e=>errors.push(e.message))
 for(const design of ['cards','wheel'])for(const theme of ['light','dark']){
  await page.goto(origin+`/preview/wash?design=${design}&theme=${theme}`);await page.locator(`.wash-kiosk[data-theme=${theme}][data-design=${design}]`).waitFor();assert.equal(await page.locator('.footer-dev-refresh').count(),0)
 }
 assert.deepEqual(requests,[]);assert.deepEqual(errors,[]);console.log('PASS production UI: no DEV refresh in both designs/themes; preview makes no hardware/payment API calls')
}finally{await browser?.close();server.kill()}
