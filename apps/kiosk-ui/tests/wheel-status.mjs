import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {lightTones,darkActiveTones,readableInk} from '../src/kiosk/program-tones.js'
const origin='http://127.0.0.1:5198',server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5198','--strictPort'],{stdio:'ignore'})
let browser
try{
 for(let i=0;i<100;i++){try{await fetch(origin);break}catch{await new Promise(r=>setTimeout(r,100))}}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
 const p=await browser.newPage({viewport:{width:1080,height:1920}}),errors=[],posts=[];p.on('pageerror',e=>errors.push(e.message))
 const ids=Object.keys(lightTones);let theme='dark',s
 const base={creditSum:25000,phase:'active',activeMode:'foam',selectedMode:'foam',armedMode:'foam',lastIoOk:true,runtimeAgeSeconds:0,pauseState:'none',remainingSeconds:500,displayTimeKind:'program'}
 await p.route('**/api/**',async r=>{if(r.request().method()!=='GET')posts.push(r.request().url());const path=new URL(r.request().url()).pathname
 const data=path==='/api/wash/state'?{ok:true,state:s,parameters:{paidPause:{enabled:true,amountSum:1000,durationSeconds:120},tariffs:Object.fromEntries(ids.map(id=>[id,{enabled:true}]))}}:path==='/api/kiosk/settings'?{ok:true,config:{programs:ids.map(id=>({id,visible:true})),theme:{design:'wheel',appearance:{mode:'manual',manualTheme:theme}}}}:{ok:true,click:{enabled:false}};await r.fulfill({json:data})})
 for(theme of ['dark','light']){
  s={...base};await p.goto(origin+'/wash');await p.locator('.wheel-status .active-program-hint').waitFor();assert.equal(await p.locator('.wash-status img').count(),0);assert.equal(await p.locator('.status-value').evaluate(e=>getComputedStyle(e).color),theme==='light'?'rgb(11, 35, 56)':'rgb(255, 255, 255)')
  const panel=p.locator('.wheel-status')
  if(theme==='light'){
   assert.equal(await p.locator('.wheel-center>circle').first().evaluate(el=>getComputedStyle(el).fill),'rgb(247, 250, 252)');
   assert.equal(await p.locator('.wheel-center .center-label').evaluate(el=>getComputedStyle(el).fill),'rgb(23, 51, 75)');
   assert.equal(await p.locator('.wheel-segment.running .segment-description').textContent(),'ISHLAYAPTI');
   assert.equal(await p.locator('.wheel-segment.running .segment-name').evaluate(el=>getComputedStyle(el).fill),'rgb(255, 255, 255)');
   assert.equal(await p.locator('.wheel-segment.running .segment-surface').evaluate(el=>getComputedStyle(el).filter),'none');
  }
  for(const id of ids){s={...base,activeMode:id,armedMode:id,selectedMode:id};const tone=(theme==='light'?lightTones:darkActiveTones)[id];await p.waitForFunction(t=>document.querySelector('.wheel-status')?.style.getPropertyValue('--status-tone')===t,tone);assert.equal(await panel.evaluate(e=>e.style.getPropertyValue('--status-ink')),readableInk(tone,theme))}
  s={...base};await p.waitForFunction(()=>document.querySelector('.wheel-status')?.style.getPropertyValue('--status-tone')===(document.querySelector('.wash-kiosk').dataset.theme==='light'?'#dc1e96':'#0089e8'));await p.screenshot({path:`../../docs/ui-wheel-status-${theme}-active.png`})
  for(const pause of ['free','paid']){s={...base,phase:'pause_'+pause,activeMode:null,selectedMode:'pause',pauseState:pause,remainingSeconds:41,displayTimeKind:pause+'_pause'};await p.locator('.wheel-status.pause-'+pause).waitFor();assert.equal(await panel.locator('svg[data-icon=pause]').count(),1);assert.equal(await panel.locator('.status-primary strong').textContent(),'00:41')}
  s={...base,creditSum:0,phase:'idle',activeMode:null,armedMode:null};await p.locator('.wheel-status .active-program-hint').waitFor({state:'hidden'});await p.screenshot({path:`../../docs/ui-wheel-status-${theme}-idle.png`});assert(await p.evaluate(()=>document.documentElement.scrollWidth===innerWidth&&document.documentElement.scrollHeight===innerHeight))
 }
 assert.deepEqual(posts,[]);assert.deepEqual(errors,[]);console.log('PASS wheel status: both themes/eight colors/neutral/pauses; no photos or commands')
}finally{await browser?.close();server.kill()}
