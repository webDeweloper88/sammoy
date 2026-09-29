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
    const error = new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg).join('; ') : `HTTP ${response.status}`)
    error.status = response.status
    if(response.status === 401 && token && path !== '/api/auth/logout') window.dispatchEvent(new Event('sammoy-session-expired'))
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
