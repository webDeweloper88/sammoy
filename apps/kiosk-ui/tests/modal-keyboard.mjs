import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
const origin='http://127.0.0.1:5211', server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5211'],{stdio:'ignore'});let browser;
try{
for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
for(const [width,height] of [[1080,1920],[1920,1080],[390,844]]){
const page=await browser.newPage({viewport:{width,height},hasTouch:true});page.on('pageerror',e=>console.error(e.message));page.on('console',m=>{if(m.type()==='error')console.error(m.text())});page.setDefaultTimeout(7000);
await page.route('**/api/**',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,complete:true})}));
await page.goto(origin+'/login');await page.getByRole('button',{name:'⟳ Перезапустить',exact:true}).tap();await page.getByLabel('Логин Owner/Admin',{exact:true}).tap();const kb=page.locator('.dialog-keyboard');await kb.getByRole('button',{name:'a',exact:true}).tap();assert.equal(await page.getByLabel('Логин Owner/Admin',{exact:true}).inputValue(),'a');
assert(await kb.getByRole('button',{name:'a',exact:true}).evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}));
const box=await kb.boundingBox();assert(box.y>=0&&box.y+box.height<=height);
await kb.getByRole('button',{name:'Далее →',exact:true}).tap();await kb.getByRole('button',{name:'b',exact:true}).tap();assert.equal(await page.getByRole('dialog').getByLabel('Пароль',{exact:true}).inputValue(),'b');await kb.getByRole('button',{name:'Готово ✓',exact:true}).tap();assert.equal(await page.locator('.touch-keyboard').count(),0);await page.getByLabel('Логин Owner/Admin',{exact:true}).tap();await page.getByRole('dialog').getByRole('button',{name:'Отмена',exact:true}).tap();await page.waitForTimeout(100);assert.equal(await page.locator('.dialog-keyboard').count(),0);await page.close();
}console.log('PASS modal keyboard: portrait/landscape/mobile touch, layering, next field, close');
}finally{await browser?.close();server.kill()}
