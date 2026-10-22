import {chromium} from 'playwright'
import {spawn} from 'node:child_process'
import assert from 'node:assert/strict'
const origin='http://127.0.0.1:5200',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5200','--strictPort'],{stdio:'ignore'})
let browser
try {
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const page=await browser.newPage({viewport:{width:1080,height:800},hasTouch:true})
 await page.route('**/scroll-harness',r=>r.fulfill({contentType:'text/html',body:`<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/src/style.css"><link rel="stylesheet" href="/src/touch.css"></head><body><div class="shell" style="height:3000px;padding:60px"><h1>Setup</h1><button id="test">No action</button><div style="height:2500px"></div></div><script type="module">import {enableManagementScroll} from '/src/management-scroll.js';enableManagementScroll();window.actions=0;document.getElementById('test').onclick=()=>window.actions++;</script></body></html>`}))
 await page.goto(origin+'/scroll-harness');await page.waitForFunction(()=>document.body.classList.contains('management-ui'))
 await page.mouse.move(30,650);await page.mouse.down();await page.mouse.move(30,250,{steps:15});await page.mouse.up()
 assert(await page.evaluate(()=>scrollY)>200,'Mouse-emulated panel must drag-scroll')
 await page.waitForTimeout(700);await page.evaluate(()=>scrollTo(0,0))
 const cdp=await page.context().newCDPSession(page)
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:30,y:650}]})
 for(let i=1;i<=12;i++)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:30,y:650-i*30}]})
 await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]})
 await page.waitForTimeout(200)
 assert(await page.evaluate(()=>scrollY)>100,'Native touch must still scroll')
 assert.equal(await page.evaluate(()=>window.actions),0)
 console.log('Management scroll: mouse-emulated panel and native touch gestures passed, no button actions')
} finally {await browser?.close();server.kill()}
