import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const html=await readFile(new URL('../public/launch.html',import.meta.url),'utf8');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
try{
 for(const [complete,failFirst] of [[false,false],[true,false],[false,true]]){
  const page=await browser.newPage();let calls=0;
  await page.route('http://factory.test/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/launch')return route.fulfill({contentType:'text/html',body:html});
   if(path==='/api/commissioning/state'){calls++;return route.fulfill({status:failFirst&&calls===1?503:200,contentType:'application/json',body:JSON.stringify({complete})})}
   return route.fulfill({contentType:'text/html',body:'<p>Destination</p>'});
  });
  await page.goto('http://factory.test/launch');
  await page.waitForURL('http://factory.test/'+(complete?'wash':'install'));
  assert.equal(calls,failFirst?2:1);await page.close();
 }
 console.log('PASS launch: fresh clone → install, commissioned → wash, service startup retry');
}finally{await browser.close()}
