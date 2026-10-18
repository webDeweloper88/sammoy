export const lightTones={water:'#079be5',foam:'#dc1e96',wax:'#e6ae00',osmos:'#8846e6',chem:'#12b7a6',nano:'#52b925',air:'#008cb8',vacuum:'#5865c9'}
export const darkTones={water:'#39c7ef',foam:'#edb85e',wax:'#bb84ee',osmos:'#ee899e',chem:'#7ed295',nano:'#efa566',air:'#39c7ef',vacuum:'#bb84ee'}
export const darkActiveTones={water:'#009fe8',foam:'#0089e8',wax:'#f3c229',osmos:'#e84178',chem:'#19b98b',nano:'#f58232',air:'#008fce',vacuum:'#7850d5'}
export const programInk=(theme,id)=>theme==='light'&&['wax','nano'].includes(id)||theme==='dark'&&['wax','nano','chem'].includes(id)?'#092438':'#ffffff'

// Consider the whole background beneath right-side labels, including the blend.
export function readableInk(hex,theme){
 const rgb=value=>value.match(/[a-f0-9]{2}/gi).map(v=>parseInt(v,16))
 const luminance=values=>{const c=values.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722}
 const ends=[luminance(rgb(hex))]
 if(theme){const base=rgb(theme==='light'?'#f8fbff':'#061522');ends.push(luminance(rgb(hex).map((v,i)=>v*.66+base[i]*.34)))}
 const score=ink=>Math.min(...ends.map(l=>(Math.max(l,luminance(rgb(ink)))+.05)/(Math.min(l,luminance(rgb(ink)))+.05)))
 if(score('#071522')>=4.5)return '#071522'
 return score('#ffffff')>=score('#000000')?'#ffffff':'#000000'
}
