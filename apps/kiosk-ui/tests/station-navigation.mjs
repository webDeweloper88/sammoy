import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
const port=5196,server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','0.0.0.0','--port',String(port),'--strictPort'],{stdio:'ignore'});let browser;
try{
for(let i=0;i<100;i++){try{await fetch('http://127.0.0.1:'+port);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
for(const [host,kiosk] of [['127.0.0.1',true],[process.env.STATION_TEST_HOST||'localhost',false]]){
 if(!kiosk&&host==='localhost')continue;
 const p=await browser.newPage(),errors=[];let loggedOut=false;p.on('pageerror',e=>errors.push(e.message));
 await p.addInitScript(()=>{if(location.pathname!=='/wash')sessionStorage.setItem('sammoy-owner-token','fixture');localStorage.setItem('sammoy-ui-language','ru')});
 await p.route('**/api/**',async r=>{const path=new URL(r.request().url()).pathname;let data={ok:true};
 if(path==='/api/auth/me')data={role:'owner',login:'owner',must_change_password:false};
 else if(path==='/api/owner/site/overview')data={complete:true,online_posts:0,posts:[],primary_post:1,primary_url:'http://10.10.10.8',manage_allowed:false,checked_at:new Date().toISOString(),summary:{}};
 else if(path==='/api/auth/logout')loggedOut=true;
 else throw Error('Unexpected API '+path);
 await r.fulfill({json:data})});
 await p.route('**/wash',r=>r.fulfill({contentType:'text/html',body:'Customer screen'}));
 await p.goto('http://'+host+':'+port+'/owner/site');
 await p.getByRole('heading',{name:'Вся мойка',exact:true}).waitFor();
 for(const width of [390,1080]){await p.setViewportSize({width,height:1920});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Header must fit viewport')}
 if(kiosk){assert.equal(await p.getByRole('link',{name:'Открыть главный пост',exact:true}).count(),0);await p.getByLabel('QR главного поста',{exact:true}).waitFor();}
 else {const link=p.getByRole('link',{name:'Открыть главный пост',exact:true});assert.equal(await link.getAttribute('target'),'_blank');assert((await link.getAttribute('rel')).includes('noopener'));}
 await p.getByRole('button',{name:'К экрану поста',exact:true}).click();
 await p.waitForURL('http://'+host+':'+port+'/wash');assert(loggedOut);assert.equal(await p.evaluate(()=>sessionStorage.getItem('sammoy-owner-token')),null);assert.deepEqual(errors,[]);await p.close();
}
console.log('PASS station navigation: kiosk QR without foreign navigation; desktop opens a separate tab; return logs out and keeps local origin');
}finally{await browser?.close();server.kill()}
