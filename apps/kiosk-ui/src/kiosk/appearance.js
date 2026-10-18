const clock = new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Tashkent',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})
const minutes = value => {
 if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(value||''))return null
 const [h,m]=value.split(':').map(Number);return h*60+m
}
export function resolveAppearance(appearance, date=new Date()) {
 if(appearance?.mode!=='auto')return appearance?.manualTheme==='light'?'light':'dark'
 const start=minutes(appearance.lightStart),end=minutes(appearance.lightEnd)
 if(start===null||end===null||start===end)return 'dark'
 const current=minutes(clock.format(date))
 return (start<end ? current>=start&&current<end : current>=start||current<end)?'light':'dark'
}
