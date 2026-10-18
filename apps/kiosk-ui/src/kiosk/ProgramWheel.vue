<script setup>
import { computed } from 'vue'
import WashIcon from './WashIcon.vue'
import {lightTones,darkTones,darkActiveTones,programInk} from './program-tones.js'
const props=defineProps({ programs:Array, selected:String, active:Boolean, disabled:Boolean, runningLabel:String,centerLabel:String, centerSub:String, centerIcon:String, centerDisabled:Boolean, pauseState:{type:String,default:'none'}, theme:{type:String,default:'dark'} })
const tones=computed(()=>props.theme==='light'?lightTones:darkTones)
const activeInk=id=>props.theme==='light'?'#ffffff':programInk(props.theme,id)
const lightRunningTones={water:'#007db8',foam:'#b91678',wax:'#8a6500',chem:'#007c70',osmos:'#7136bd',nano:'#367816',air:'#007d99',vacuum:'#5149ac'}
const activeTones=computed(()=>props.theme==='light'?lightRunningTones:darkActiveTones)
const emit=defineEmits(['select','center'])
const point=(r,a)=>[500+r*Math.cos(a*Math.PI/180),500+r*Math.sin(a*Math.PI/180)]
const segments=computed(()=>{
 const n=props.programs.length
 return props.programs.map((p,i)=>{
  const mid=-90+i*360/n, start=mid-180/n+1.7,end=mid+180/n-1.7
  const pos=point(328,mid),large=end-start>180?1:0
  const path=`M${point(478,start+2)} A478 478 0 ${large} 1 ${point(478,end-2)} Q${point(478,end)} ${point(460,end)} L${point(198,end)} Q${point(180,end)} ${point(180,end-5)} A180 180 0 ${large} 0 ${point(180,start+5)} Q${point(180,start)} ${point(198,start)} L${point(460,start)} Q${point(478,start)} ${point(478,start+2)}Z`
  return {...p,x:pos[0],y:pos[1],path}
 })
})
const orderedSegments=computed(()=>[...segments.value].sort((a,b)=>Number(a.id===props.selected)-Number(b.id===props.selected)))
function choose(p){if(!props.disabled)emit('select',p.id)}
function lines(text){const words=text.split(' ');let a='',b='';for(const w of words){if((a+' '+w).length<=22&&!b)a+=(a?' ':'')+w;else b+=(b?' ':'')+w}return [a,b]}
</script>
<template>
 <svg :class="{'has-selection':!!selected,'has-active':active,'dark-wheel':theme==='dark'}" class="program-wheel" viewBox="0 0 1000 1000" role="group" aria-label="Programs">
  <defs><linearGradient id="segment-matte" x1="0" y1="0" x2=".8" y2="1"><stop stop-color="#28333d"/><stop offset="1" stop-color="#151d24"/></linearGradient><linearGradient v-for="p in programs" :key="p.id" :id="'segment-tone-'+p.id" x1="0" y1="0" x2="1" y2="1"><stop :stop-color="tones[p.id] || '#39c7ef'" :stop-opacity="theme==='light' && active ? 0.06 : 0.17"/><stop offset="1" :stop-color="theme==='light'?'#ffffff':'#101a20'"/></linearGradient><linearGradient v-for="p in programs" :key="'active-'+p.id" :id="'segment-active-'+p.id" x1="0" y1="0" x2=".8" y2="1"><stop :stop-color="activeTones[p.id]"/><stop offset="1" :stop-color="`color-mix(in srgb,${activeTones[p.id]} 86%,#102735)`"/></linearGradient></defs>
  <g v-for="p in orderedSegments" :key="p.id" :style="{'--program-tone':tones[p.id] || '#39c7ef','--active-ink':active?activeInk(p.id):(props.theme==='light'?'#0b2338':'#f4f7fa'),'--active-tone':activeTones[p.id]}" :transform="active&&selected===p.id?`translate(${p.x} ${p.y}) scale(1.025) translate(${-p.x} ${-p.y})`:undefined" class="wheel-segment" :class="{selected:selected===p.id,running:active&&selected===p.id,unavailable:disabled}" role="button" :aria-label="p.label" :aria-pressed="selected===p.id" :aria-disabled="disabled" :tabindex="disabled?-1:0" @click="choose(p)" @keydown.enter.prevent="choose(p)" @keydown.space.prevent="choose(p)">
   <path class="segment-surface" :style="{fill:theme==='dark'&&selected&&selected!==p.id?'url(#segment-matte)':`url(#segment-${selected===p.id&&active?'active':'tone'}-${p.id})`}" :d="p.path" />
   <path v-if="selected===p.id" class="segment-inset" :d="p.path" :transform="`translate(${p.x} ${p.y}) scale(.95) translate(${-p.x} ${-p.y})`" pointer-events="none"/>
   <g :transform="`translate(${p.x},${p.y})`" pointer-events="none">
    <WashIcon :name="p.id" x="-36" y="-77" width="72" height="72" />
    <text class="segment-name" y="31" text-anchor="middle">{{ p.label }}</text>
    <text class="segment-description" y="62" text-anchor="middle"><tspan :x="0">{{active&&selected===p.id&&theme==='light'?runningLabel:lines(p.description)[0]}}</tspan><tspan v-if="!(active&&selected===p.id&&theme==='light')" :x="0" dy="25">{{ lines(p.description)[1] }}</tspan></text>
   </g>
  </g>
  <g class="wheel-center" :class="{unavailable:centerDisabled,'pause-free':pauseState==='free','pause-paid':pauseState==='paid','pause-stopped':pauseState==='stopped'}" role="button" :aria-label="centerLabel" :aria-disabled="centerDisabled" :tabindex="centerDisabled?-1:0" @click="!centerDisabled && emit('center')" @keydown.enter.prevent="!centerDisabled && emit('center')" @keydown.space.prevent="!centerDisabled && emit('center')">
   <circle cx="500" cy="500" r="159" fill="#102b3a" stroke="#13b8ff" stroke-width="3"/>
   <circle cx="500" cy="500" r="147" fill="none" stroke="#334a58"/>
   <WashIcon :name="centerIcon || 'pause'" x="468" y="416" width="64" height="64" pointer-events="none"/>
   <text x="500" y="518" text-anchor="middle" class="center-label" :class="{'center-label-long':centerLabel.length>11}">{{ centerLabel }}</text>
   <text x="500" y="552" text-anchor="middle" class="center-sub"><tspan x="500">{{ lines(centerSub)[0] }}</tspan><tspan v-if="lines(centerSub)[1]" x="500" dy="22">{{ lines(centerSub)[1] }}</tspan></text>
  </g>
 </svg>
</template>
<style scoped>
.program-wheel{width:100%;height:100%;overflow:visible;display:block;color:#f4f7fa;touch-action:manipulation}.segment-surface{fill:url(#segment-matte);stroke:var(--program-tone);stroke-width:1.8;stroke-linejoin:round;transition:fill .25s,stroke .25s}.wheel-segment,.wheel-center{cursor:pointer;outline:none;-webkit-tap-highlight-color:transparent}.wheel-segment.selected .segment-surface{fill:#075780;stroke:#24c8ff;stroke-width:3}.wheel-segment:not(.selected) svg{color:var(--program-tone)}.wheel-segment:active .segment-surface{fill:#244e63}.wheel-segment:focus-visible .segment-surface{stroke:#fff;stroke-width:5}.wheel-center:focus-visible circle{stroke:#fff}.segment-name{fill:currentColor;font-size:32px;font-weight:700}.segment-description{fill:#adbecb;font-size:23px}.center-label{fill:currentColor;font-size:31px;font-weight:700}.center-label-long{font-size:24px}.center-sub{fill:#a8b3bf;font-size:22px}.unavailable{opacity:.42;cursor:default}.wheel-center:active:not(.unavailable)>circle:first-child{fill:#24516a}
</style>

<style scoped>
.wheel-segment.selected{color:var(--active-ink)}
.wheel-segment.selected .segment-surface{stroke:var(--program-tone);stroke-width:5;filter:drop-shadow(0 0 9px color-mix(in srgb,var(--program-tone) 55%,transparent))}
.segment-inset{fill:none;stroke:var(--active-ink);stroke-width:2.8;opacity:.9}
.wheel-segment.selected .segment-description{fill:var(--active-ink)}
.wheel-segment.selected:not(.running) .segment-surface{filter:none}
.wheel-segment.selected:not(.running) .segment-inset{stroke-dasharray:8 6;opacity:.65}
@media(prefers-reduced-motion:reduce){.segment-surface{transition:none}}
</style>

<style scoped>
.dark-wheel.has-selection .wheel-segment:not(.selected) .segment-surface{stroke:#647b8b;stroke-width:1.8}
.dark-wheel.has-selection .wheel-segment:not(.selected) svg{color:#c0d0dc}
.dark-wheel .wheel-segment.selected .segment-surface{stroke:var(--active-tone);stroke-width:8;filter:drop-shadow(0 0 12px color-mix(in srgb,var(--active-tone) 65%,transparent))}
.dark-wheel .wheel-segment.selected .segment-inset{stroke-width:5;opacity:1}
.dark-wheel .wheel-segment.selected .segment-name{font-size:38px;font-weight:800}
.dark-wheel .wheel-segment.selected:not(.running) .segment-surface{filter:none}
</style>

<style scoped>
.program-wheel.has-active .wheel-segment:not(.selected){opacity:.8}
.wheel-segment.selected:not(.running) .segment-description{fill:var(--active-ink)}
.wheel-center.pause-free,.wheel-center.pause-paid,.wheel-center.pause-stopped{color:#092438}
.wheel-center.pause-free>circle:first-child,.wheel-center.pause-paid>circle:first-child{filter:drop-shadow(0 0 10px #ffab324d)}
.wheel-center.pause-free .center-sub,.wheel-center.pause-paid .center-sub,.wheel-center.pause-stopped .center-sub{font-size:20px;font-weight:700}
</style>

<style scoped>
.program-wheel:not(.dark-wheel).has-active .wheel-segment:not(.selected){opacity:1;color:#344d63}
.program-wheel:not(.dark-wheel) .wheel-segment.running .segment-surface{stroke:var(--active-tone);stroke-width:7;filter:none}
.program-wheel:not(.dark-wheel) .wheel-segment.running .segment-inset{stroke:#fff;stroke-width:3;opacity:1}
.program-wheel:not(.dark-wheel) .wheel-segment.running .segment-name{font-size:38px;font-weight:800}
.program-wheel:not(.dark-wheel) .wheel-segment.running .segment-description{font-size:21px;font-weight:700;letter-spacing:.7px}
</style>
