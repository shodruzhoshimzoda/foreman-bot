import { mockDashboard, mockSetStatus, mockTask, mockTasks } from './mock.js'

export const tg = window.Telegram?.WebApp
export const MOCK = import.meta.env.VITE_MOCK === '1'

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message)
    this.status = status
    this.data = data // тело ответа с ошибкой (например, актуальная задача при 409)
  }
}

async function call(path, signal, body) {
  if (!tg?.initData) throw new ApiError(401, 'no-telegram')
  let res
  try {
    res = await fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: { Authorization: `tma ${tg.initData}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError(0, 'network')
  }
  if (!res.ok) {
    const text = await res.text()
    let data
    try { data = JSON.parse(text) } catch { /* не JSON */ }
    throw new ApiError(res.status, text, data)
  }
  return res.json()
}

const delay = (ms) => new Promise((r) => setTimeout(r, ms))

export async function fetchDashboard(days, signal) {
  if (MOCK) {
    await delay(250)
    return mockDashboard(days)
  }
  return call(`/api/dashboard?days=${days}`, signal)
}

export async function fetchTasks({ status, foreman, before } = {}, signal) {
  if (MOCK) {
    await delay(300)
    return mockTasks({ status, foreman, before })
  }
  const q = new URLSearchParams()
  if (status) q.set('status', status)
  if (foreman) q.set('foreman', foreman)
  if (before) q.set('before', before)
  return call(`/api/tasks?${q}`, signal)
}

// Ссылка на медиа подписана сервером; дополнительные параметры (?v=thumb, ?fmt=m4a) подпись не меняют.
export function mediaSrc(url, extra = {}) {
  if (!url || url.startsWith('data:')) return url
  const q = new URLSearchParams(extra).toString()
  return q ? `${url}&${q}` : url
}

// Отметка результата: done | failed | cancelled, либо new — вернуть закрытую задачу в работу
export async function setTaskStatus(id, status) {
  if (MOCK) {
    await delay(250)
    return mockSetStatus(id, status)
  }
  return call(`/api/tasks/${id}/status`, undefined, { status })
}

// Одна задача целиком (панель задачи): полный текст, все вложения
export async function fetchTask(id, signal) {
  if (MOCK) {
    await delay(200)
    return mockTask(id)
  }
  return call(`/api/tasks/${id}`, signal)
}
