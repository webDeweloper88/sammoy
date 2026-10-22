import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
const origin='http://127.0.0.1:5203',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5203','--strictPort'],{stdio:'ignore'});let browser;
try{
for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});const page=await browser.newPage();let status=200,payload={complete:false},customerCalls=0;const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async r=>{const path=new URL(r.request().url()).pathname;if(path==='/api/commissioning/state'){await r.fulfill({status,json:payload,headers:{'Cache-Control':'no-store'}});return;}customerCalls++;await r.fulfill({json:{}})});
for(const path of ['/install','/launch'])await page.route('**'+path,r=>r.fulfill({contentType:'text/html',body:'<h1>'+path+'</h1>'}));
for(const path of ['/wash','/','/wash/','/wash?from=bookmark']){await page.goto(origin+path);await page.waitForURL(origin+'/install');assert.equal(customerCalls,0);assert.equal(await page.locator('.wash-kiosk').count(),0)}
status=503;await page.goto(origin+'/wash');await page.waitForURL(origin+'/launch');assert.equal(customerCalls,0);
status=200;payload={};await page.goto(origin+'/wash');await page.waitForURL(origin+'/launch');assert.equal(customerCalls,0);
assert.deepEqual(errors,[]);console.log('PASS customer setup gate: root, wash, slash and bookmark redirect before mounting; unavailable or invalid state goes to launch; no customer API calls before setup');
}finally{await browser?.close();server.kill()}
