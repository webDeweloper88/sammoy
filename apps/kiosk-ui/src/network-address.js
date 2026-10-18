export function maskFromPrefix(prefix) {
  if(!Number.isInteger(Number(prefix)) || Number(prefix)<0 || Number(prefix)>32) throw Error('Invalid subnet prefix')
  let bits=Number(prefix)
  return Array.from({length:4},()=>{const n=Math.min(8,bits);bits-=n;return n?256-2**(8-n):0}).join('.')
}
export function prefixFromMask(mask) {
  const parts=String(mask).trim().split('.')
  if(parts.length!==4 || parts.some(p=>!/^\d{1,3}$/.test(p)||Number(p)>255)) throw Error('Invalid subnet mask')
  const bits=parts.map(p=>Number(p).toString(2).padStart(8,'0')).join('')
  if(!/^1*0*$/.test(bits)) throw Error('Subnet mask must be contiguous')
  const prefix=bits.indexOf('0')===-1?32:bits.indexOf('0')
  if(prefix<8||prefix>30) throw Error('Subnet prefix must be 8–30')
  return prefix
}
