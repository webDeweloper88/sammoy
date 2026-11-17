import {maintenanceActive} from './maintenance-state.js'
export async function api(path, { token, ...options } = {}) {
  const response = await fetch(path, {
    signal: AbortSignal.timeout(60000),
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers
    }
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.ok === false) {
    const detail = data.detail
    if(response.status===428 && detail==='owner_password_required' && token && !options.headers?.['X-Owner-Confirmation']){
      const password=await new Promise(resolve=>window.dispatchEvent(new CustomEvent('sammoy-owner-confirmation',{detail:{resolve}})))
      if(password===null)throw new Error(serviceMessage('service_cancelled'))
      const result=await api('/api/auth/confirm-action',{token,method:'POST',body:JSON.stringify({password,method:options.method||'GET',path:path.split('?')[0],body:options.body||''})})
      return api(path,{token,...options,headers:{...options.headers,'X-Owner-Confirmation':result.grant}})
    }
    const error = new Error(typeof detail === 'string' ? serviceMessage(detail) : Array.isArray(detail) ? detail.map(item => item.msg).join('; ') : `HTTP ${response.status}`)
    error.status = response.status
    if(response.status === 401 && token && path !== '/api/auth/logout' && !maintenanceActive.value) window.dispatchEvent(new Event('sammoy-session-expired'))
    throw error
  }
  return data
}

export const login = (name, password) => api('/api/auth/login', {
  method: 'POST', body: JSON.stringify({ login: name, password })
})
export const me = token => api('/api/auth/me', { token })
export const changePassword = (token, currentPassword, newPassword) => api('/api/auth/account', {
  token, method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
})
export const getParameters = token => api('/api/owner/wash/parameters', { token })
export const saveParameters = (token, parameters) => api('/api/owner/wash/parameters', {
  token, method: 'POST', body: JSON.stringify({ parameters })
})

const serviceErrors={
 service_card_in_use:['Карта уже служебная или недоступна для перевода','Karta xizmat kartasi yoki o‘tkazish mumkin emas','Card is already a service card or cannot be converted'],
 service_card_not_customer:['VIP-карту нельзя сделать служебной','VIP kartani xizmat kartasiga aylantirib bo‘lmaydi','A VIP card cannot become a service card'],
 service_card_has_balance:['На карте есть деньги. Сначала используйте или верните остаток.','Kartada pul bor. Avval qoldiqni ishlating yoki qaytaring.','Card has money. Use or return its balance first.'],
 service_card_pending:['У карты есть незавершённый сеанс или операция','Kartada tugallanmagan seans yoki amal bor','Card has an unfinished session or operation'],
 service_card_shared:['Карта общего кошелька: используйте локальную карту без денег','Umumiy hamyon kartasi: pulsiz mahalliy kartani ishlating','Shared-wallet card: use a local card with no money'],
 service_wallet_unavailable:['Кошелёк недоступен. Повторите позже.','Hamyon mavjud emas. Keyinroq takrorlang.','Wallet unavailable. Try later.'],
 service_pin_invalid:['Неверный PIN','PIN noto‘g‘ri','Incorrect PIN'],
 service_pin_locked:['PIN заблокирован на 5 минут','PIN 5 daqiqaga bloklandi','PIN locked for 5 minutes'],
 service_password_locked:['Пароль заблокирован на 5 минут','Parol 5 daqiqaga bloklandi','Password locked for 5 minutes'],
 service_password_invalid:['Неверный пароль Owner','Owner paroli noto‘g‘ri','Incorrect Owner password'],
 service_challenge_expired:['Время входа истекло. Приложите карту снова.','Kirish vaqti tugadi. Kartani qayta qo‘ying.','Sign-in expired. Present the card again.'],
 service_card_disabled:['Карта отозвана','Karta bekor qilingan','Card revoked'],
 service_owner_unavailable:['Войдите по логину и паролю Owner','Owner login va paroli bilan kiring','Sign in with Owner login and password'],
 service_station_busy:['Пост занят. Завершите сеанс мойки.','Post band. Yuvish seansini yakunlang.','Station busy. Finish the wash session.'],
 service_enrollment_expired:['Время регистрации истекло. Начните заново.','Ro‘yxatdan o‘tish vaqti tugadi. Qayta boshlang.','Enrollment expired. Start again.'],
 service_session_expired:['Сеанс входа по карте завершён','Karta orqali kirish seansi tugadi','Card sign-in session expired'],
 service_cancelled:['Действие отменено','Amal bekor qilindi','Action cancelled'],
 owner_password_required:['Нужен пароль Owner','Owner paroli kerak','Owner password required']
}
export function serviceMessage(code){const lang=localStorage.getItem('sammoy-ui-language')||'ru';return serviceErrors[code]?.[{ru:0,uz:1,en:2}[lang]??0]||code}
