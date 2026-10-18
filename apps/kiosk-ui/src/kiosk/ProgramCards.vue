<script setup>
import {dryFogTones} from './dry-fog.js'
import {computed} from 'vue'
import {modePhoto} from './theme2-media.js'
import WashIcon from './WashIcon.vue'
const props=defineProps({heading:String,programs:Array,selected:String,active:Boolean,disabled:Boolean,t:Object,centerLabel:String,centerSub:String,centerDisabled:Boolean,centerIcon:String,pauseState:String,language:String})
const emit=defineEmits(['select','center'])
const order=['aroma_1','aroma_2','aroma_3','aroma_4','aroma_5','water','foam','wax','chem','osmos','nano']
const ordered=computed(()=>[...props.programs].sort((a,b)=>order.indexOf(a.id)-order.indexOf(b.id)))
const tones={...dryFogTones,water:'#008dce',foam:'#db0062',wax:'#a96a00',chem:'#268237',osmos:'#0087ad',nano:'#7441ce'}
const headingText=computed(()=>({uz:'YUVISH REJIMLARI',ru:'ПРОГРАММЫ МОЙКИ',kz:'ЖУУ БАҒДАРЛАМАЛАРЫ',ky:'ЖУУ ПРОГРАММАЛАРЫ'}[props.language]))
</script>
<template>
<section class="program-cards" :class="{'has-running':active}" :aria-label="heading||headingText">
 <h2>{{heading||headingText}}<span>{{t.choose}}</span></h2>
 <div class="program-card-grid">
  <button v-for="p in ordered" :key="p.id" class="program-card" :class="{selected:selected===p.id,running:active&&selected===p.id}" :style="{'--card-tone':tones[p.id]}" :aria-label="p.label" :aria-pressed="selected===p.id" :disabled="disabled" @click="emit('select',p.id)">
   <img class="mode-photo" :src="modePhoto(p.id)" alt="" decoding="async"/><span class="program-card-icon"><WashIcon :name="p.id"/></span><span class="program-card-copy"><strong>{{p.label}}</strong><small>{{p.description}}</small></span>
   <span v-if="selected===p.id" class="program-card-state"><span v-if="active" class="mode-running-dot" aria-hidden="true"></span>{{active?t.running:t.trigger}}</span>
  </button>
 </div>
 <button v-if="selected" class="card-pause" :class="{'pause-free':pauseState==='free','pause-paid':pauseState==='paid','pause-stopped':pauseState==='stopped'}" :aria-label="centerLabel" :disabled="centerDisabled" @click="emit('center')"><WashIcon :name="centerIcon"/><span><strong>{{centerLabel}}</strong><small v-if="centerSub">{{centerSub}}</small></span></button>
</section>
</template>
