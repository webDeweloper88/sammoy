import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
const origin = 'http://127.0.0.1:5183';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5183', '--strictPort'], {stdio:'ignore'});
process.on('exit', () => server.kill());
for(let i=0;i<80;i++){try{await fetch(origin);break}catch{await new Promise(resolve=>setTimeout(resolve,100))}}
const browser = await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE || undefined,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const live = {parameters:{billPulseSum:1000,coinPulseSum:1000,freePauseSeconds:60,triggerGraceSeconds:1,triggerResetConfirmSeconds:0.5,powerRecoverySeconds:600,requireTotalStopTrigger:true,paidPause:{enabled:true,amountSum:1000,durationSeconds:120},tariffs:Object.fromEntries(['water','foam','osmos','nano','wax','chem','vacuum','air'].map(mode=>[mode,{amountSum:1000,durationSeconds:20,enabled:true}]))}};
for (const [width,height] of [[1080,1920],[1920,1080]]) {
 const context=await browser.newContext({viewport:{width,height},hasTouch:true});
 const page=await context.newPage();
 let saved, loginSeen=false;
 const errors=[];page.on('pageerror',err=>errors.push(err.message));
 await page.route('**/api/**',async route=>{
   const req=route.request(),path=new URL(req.url()).pathname;
   let body;
   if(path==='/api/auth/login') {
     const data=req.postDataJSON();assert.equal(data.login,'owner');assert.equal(data.password,'Ab1!');loginSeen=true;
     body={access_token:'test-token',user:{role:'owner',must_change_password:false}};
   } else if(path==='/api/owner/wash/parameters'){
     if(req.method()==='POST')saved=req.postDataJSON().parameters;
     body={ok:true,parameters:saved||live.parameters};
   } else throw new Error('Unexpected API request '+path);
   await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(origin+'/login');
 const keyboard=page.locator('.touch-keyboard');
 await keyboard.waitFor();
 const key=label=>keyboard.getByRole('button',{name:label,exact:true});
 for(const char of 'owner')await key(char).tap();
 await key('Далее →').tap();
 await key('⇧ Shift').tap();await key('A').tap();await key('⇧ Shift').tap();
 await key('b').tap();await key('1').tap();await key('#+=').tap();await key('!').tap();
 assert.equal(await page.getByLabel('Пароль',{exact:true}).inputValue(),'Ab1!');
 await key('Готово ✓').tap();
 // Reopening the same field after Done must work.
 await page.getByLabel('Пароль',{exact:true}).tap();await keyboard.waitFor();await key('Готово ✓').tap();
 await page.getByRole('button',{name:'Войти',exact:true}).tap();
 await page.waitForURL('**/owner/parameters');assert(loginSeen);
 const input=page.getByLabel('Подтверждение отпущенного курка, сек');
 await input.tap();await key('Очистить').tap();await key('0').tap();await key('.').tap();await key('8').tap();
 assert.equal(await input.inputValue(),'0.8');
 await key('Готово ✓').tap();
 await page.getByRole('button',{name:'Сохранить',exact:true}).first().tap();
 await page.getByRole('status').waitFor();assert.equal(saved.triggerResetConfirmSeconds,0.8);
 assert.equal(saved.powerRecoverySeconds,live.parameters.powerRecoverySeconds);
 assert.equal(saved.billPulseSum,live.parameters.billPulseSum);
 assert.deepEqual(errors,[]);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 console.log(`PASS ${width}x${height}: touch-only login, Shift/symbols, reopen keyboard, decimal editing, save payload`);
 await context.close();
}
// First-login password change must also work exclusively by touch.
const context=await browser.newContext({viewport:{width:1920,height:1080},hasTouch:true});
const page=await context.newPage();
let changed=false;
await page.route('**/api/**',async route=>{
 const path=new URL(route.request().url()).pathname;
 let body;
 if(path==='/api/auth/login')body={access_token:'change-token',user:{role:'admin',must_change_password:true}};
 else if(path==='/api/auth/account'){
  const data=route.request().postDataJSON();assert.equal(data.current_password,'oldpass1');assert.equal(data.new_password,'newpass2');changed=true;
  body={access_token:'new-token',user:{role:'admin',must_change_password:false}};
 }else if(path==='/api/owner/wash/parameters')body={ok:true,parameters:live.parameters};
 else if(path==='/api/admin/diagnostics')body={state:{creditSum:0},simulation:{},parameters:{billPulseSum:1000},system:{disk_free_bytes:1},io:{available:false},configuration:{available:false},rfid:{available:false}};
 else throw Error('Unexpected API call '+path);
 await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
});
await page.goto(origin+'/login');
const keyboard=page.locator('.touch-keyboard');await keyboard.waitFor();
const key=name=>keyboard.getByRole('button',{name,exact:true});
for(const char of 'admin')await key(char).tap();
await key('Далее →').tap();for(const char of 'oldpass1')await key(char).tap();
await key('Готово ✓').tap();await page.getByRole('button',{name:'Войти',exact:true}).tap();
await page.getByLabel('Новый пароль (от 8 символов)',{exact:true}).tap();
for(const char of 'newpass2')await key(char).tap();await key('Далее →').tap();
for(const char of 'newpass2')await key(char).tap();await key('Готово ✓').tap();
await page.getByRole('button',{name:'Сменить пароль',exact:true}).tap();
await page.waitForURL('**/admin/diagnostics');assert(changed);
console.log('PASS: mandatory password change and confirmation by touch');
await context.close();
await browser.close();
server.kill();
