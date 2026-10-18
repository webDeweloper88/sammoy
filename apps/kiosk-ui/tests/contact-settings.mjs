import {chromium} from 'playwright';import assert from 'node:assert/strict';import {spawn} from 'node:child_process'
const origin='http://127.0.0.1:5200',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5200','--strictPort'],{stdio:'ignore'});let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});const p=await browser.newPage();let saved
 await p.route(origin+'/fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body><div id="fixture"></div></body></html>'}))
 await p.route('**/api/**',r=>{assert.equal(r.request().headers().authorization,'Bearer test-token');if(r.request().method()==='POST')saved=r.request().postDataJSON();return r.fulfill({json:{ok:true,settings:saved||{enabled:false,phone:'',chat_id:'',marketing:'',programmer:'',electrician:'',telegram:'',instagram:'',youtube:''}}})})
 for(const kind of ['operator','manufacturer']){
  saved=null;await p.goto(origin+'/fixture');await p.evaluate(async kind=>{const {createApp}=await import('/node_modules/.vite/deps/vue.js');const {default:C}=await import('/src/ContactSettings.vue');createApp(C,{kind,token:'test-token',language:'ru'}).mount('#fixture')},kind)
  if(kind==='operator'){await p.getByLabel('Показывать вызов оператора',{exact:true}).check();await p.getByLabel('Телефон оператора',{exact:true}).fill('+998 90 123 45 67');await p.getByLabel('Telegram chat ID',{exact:true}).fill('-100123');await p.getByRole('button',{name:'Сохранить оператора',exact:true}).click();await p.getByText('Сохранено',{exact:true}).waitFor();assert.equal(saved.enabled,true);assert.equal(saved.chat_id,'-100123')}
  else {await p.getByLabel('Продажи и сотрудничество',{exact:true}).fill('+998 91 111 69 29');await p.getByRole('button',{name:'Сохранить контакты LABRIX',exact:true}).click();await p.getByText('Сохранено',{exact:true}).waitFor();assert.equal(saved.marketing,'+998 91 111 69 29')}
 }
 console.log('PASS contact forms: Owner operator and Admin manufacturer read/edit/save through authenticated APIs')
}finally{await browser?.close();server.kill()}
