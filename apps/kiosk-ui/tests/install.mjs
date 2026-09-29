import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
const origin='http://127.0.0.1:5185',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5185','--strictPort'],{stdio:'ignore'});let browser;
try{
for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});const page=await browser.newPage({viewport:{width:1920,height:1080},hasTouch:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));let credit=1744,claimed=false,completed=false;
const state={ok:true,hardware:{complete:true},io_ready:true,commissioning:{complete:false},site:{site_code:'',post_no:1,gateway_url:'https://gateway.example.com'},license:{locked:false}};
await page.route('**/api/**',async route=>{const req=route.request(),path=new URL(req.url()).pathname;let data;
if(path==='/api/wash/state')data={state:{activeMode:null,creditSum:credit}};
else if(path==='/api/commissioning/status')data=state;
else if(path==='/api/commissioning/claim'){assert.equal(req.postDataJSON().activation_code,'ABCD1234');assert.equal(credit,0);claimed=true;state.site.site_code='SITE-1';data=state;}
else if(path==='/api/commissioning/complete'){assert.equal(req.postDataJSON().confirmation,'READY');assert(claimed);completed=true;state.commissioning.complete=true;data=state;}
else throw Error(path);
await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
await page.goto(origin+'/install');const activate=page.getByRole('button',{name:'Активировать пост',exact:true});await activate.waitFor();assert(await activate.isDisabled());credit=0;await page.getByRole('button',{name:'Обновить',exact:true}).last().tap();await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(e=>e.textContent==='Активировать пост')?.disabled);
await page.getByLabel('Адрес сервера активации',{exact:true}).fill('https://activation.invalid');await page.getByLabel('Код активации поста',{exact:true}).tap();const kb=page.locator('.touch-keyboard');const key=name=>kb.getByRole('button',{name,exact:true});await key('⇧ Shift').tap();for(const c of 'ABCD1234')await key(c).tap();await key('Готово ✓').tap();await activate.tap();await page.getByText('Пост активирован. Проверьте данные и завершите установку.').waitFor();assert(claimed);await page.getByRole('button',{name:'Завершить установку',exact:true}).tap();assert(!completed);await page.getByRole('button',{name:'Подтвердить',exact:true}).tap();await page.getByText('Установка этого поста завершена.',{exact:true}).waitFor();assert(completed);assert.deepEqual(errors,[]);console.log('PASS install: outstanding credit blocks activation, touch activation code, explicit completion confirmation');
}finally{await browser?.close();server.kill()}
