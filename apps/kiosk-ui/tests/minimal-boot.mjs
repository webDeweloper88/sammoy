import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
try{
 const page=await browser.newPage({viewport:{width:1080,height:1920}});let attempts=0;
 await page.route('**/labrix.png',async r=>r.fulfill({contentType:'image/png',body:await readFile(new URL('../public/assets/theme2/brand/labrix_mark_L.png',import.meta.url))}));
 await page.route('http://127.0.0.1/**',async r=>{attempts++;if(attempts<=2)return r.abort('connectionrefused');return r.fulfill({contentType:'text/html',body:'<p>Local UI ready</p>'})});
 await page.goto(new URL('../../../deploy/minimal-kiosk/boot.html',import.meta.url).href);
 await page.getByRole('heading',{name:'LABRIX',exact:true}).waitFor();
 await page.locator('img').evaluate(i=>i.decode());
 assert(await page.locator('img').evaluate(i=>i.naturalWidth>0));
 await page.waitForURL('http://127.0.0.1/launch');assert(attempts>=4);
 console.log('PASS local boot splash remains during connection failure, then enters local launch screen');
}finally{await browser.close()}
