export function formatActivationCode(value) {
  return String(value).toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,16).match(/.{1,4}/g)?.join('-') || ''
}

export function formatActivationInput(input) {
  const digits= input.value.slice(0,input.selectionStart??input.value.length).replace(/[^a-z0-9]/gi,'').length
  const formatted=formatActivationCode(input.value)
  input.value=formatted
  const caret=Math.min(formatted.length,digits+Math.floor(Math.max(0,digits-1)/4))
  input.setSelectionRange(caret,caret)
  return formatted
}

export function activationBeforeInput(event) {
  const input=event.target,start=input.selectionStart,end=input.selectionEnd
  if(start!==end)return
  let value,position
  if(event.inputType==='deleteContentBackward'&&input.value[start-1]==='-') {
    value=input.value.slice(0,start-2)+input.value.slice(start);position=start-2
  } else if(event.inputType==='deleteContentForward'&&input.value[start]==='-') {
    value=input.value.slice(0,start)+input.value.slice(start+2);position=start
  } else return
  event.preventDefault();input.value=value;input.setSelectionRange(position,position)
  input.dispatchEvent(new Event('input',{bubbles:true}))
}

export function ipv4(value) {
  if(!/^\d{1,3}(\.\d{1,3}){3}$/.test(value))return null
  const parts=value.split('.').map(Number)
  return parts.every(v=>v>=0&&v<=255)?parts:null
}

export function networkContext(status,hostname) {
  const connected=(status?.interfaces||[]).filter(i=>i.connected&&ipv4(i.address))
  const selected=connected.find(i=>i.address===hostname)||connected.find(i=>i.interface==='eth0')||connected[0]
  const address=selected?.address||(ipv4(hostname)&&hostname!=='127.0.0.1'?hostname:'')
  return {address,prefix:selected?.prefix??null,stem:address?address.split('.').slice(0,3).join('.')+'.':''}
}

export function subnetHost(address,context) {
  const ip=ipv4(address),local=ipv4(context.address),prefix=context.prefix
  if(!ip||!local||!Number.isInteger(prefix)||prefix<1||prefix>30)return true
  const number=p=>p.reduce((n,v)=>(n*256+v)>>>0,0)
  const mask=(0xffffffff<<(32-prefix))>>>0,network=(number(local)&mask)>>>0,host=number(ip)
  return ((host&mask)>>>0)===network&&host!==network&&host!==((network|(~mask>>>0))>>>0)
}
