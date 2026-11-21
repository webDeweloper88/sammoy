const time = new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Tashkent',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})
const date = new Intl.DateTimeFormat('ru-RU', {timeZone:'Asia/Tashkent',day:'2-digit',month:'2-digit',year:'numeric'})
export function headerClock(timestamp){return {time:time.format(timestamp),date:date.format(timestamp)}}
