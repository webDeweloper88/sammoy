import assert from 'node:assert/strict'
import {api} from '../src/api.js'
globalThis.localStorage={getItem:()=> 'ru'}
let confirmPassword='owner-test-password',events=[]
globalThis.window={dispatchEvent:event=>{events.push(event.type);if(event.type==='sammoy-owner-confirmation')event.detail.resolve(confirmPassword)}}
globalThis.CustomEvent=class{constructor(type,options){this.type=type;this.detail=options.detail}}
const reply=(status,data)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}})
let calls=[]
globalThis.fetch=async(path,options)=>{
 calls.push({path,options})
 if(path==='/api/auth/confirm-action')return reply(200,{grant:'single-action-grant'})
 if(!options.headers['X-Owner-Confirmation'])return reply(428,{detail:'owner_password_required'})
 return reply(200,{ok:true})
}
const body=JSON.stringify({post:2,confirmation:'PROMOTE'})
assert.deepEqual(await api('/api/owner/wallet/promote',{token:'nfc-token',method:'POST',body}),{ok:true})
assert.equal(calls.length,3)
assert.deepEqual(JSON.parse(calls[1].options.body),{password:'owner-test-password',method:'POST',path:'/api/owner/wallet/promote',body})
assert.equal(calls[2].options.body,body)
assert.equal(calls[2].options.headers.Authorization,'Bearer nfc-token')
assert.equal(calls[2].options.headers['X-Owner-Confirmation'],'single-action-grant')
assert(!events.includes('sammoy-session-expired'))
confirmPassword=null;calls=[]
await assert.rejects(api('/api/owner/wallet/promote',{token:'nfc-token',method:'POST',body}),/Действие отменено/)
assert.equal(calls.length,1)
globalThis.fetch=async()=>reply(403,{detail:'service_pin_invalid'})
await assert.rejects(api('/api/auth/service-pin',{method:'POST',body:'{}'}),/Неверный PIN/)
console.log('Service access request confirmation and cancellation: passed')
