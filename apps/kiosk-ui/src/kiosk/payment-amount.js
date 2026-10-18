export function editPaymentAmount(amount,key,replace) {
 if(key==='C')return {amount:'',replace:false}
 if(key==='⌫')return {amount:amount.slice(0,-1),replace:false}
 if(!/^[0-9]$/.test(key))return {amount,replace}
 const base=replace||amount==='0'?'':amount
 return {amount:base.length<8?base+key:base,replace:false}
}
