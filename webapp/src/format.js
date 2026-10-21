export const STATUS = {
  new: { label: 'В работе', icon: '🔧', color: 'var(--c-active)' },
  done: { label: 'Выполнена', icon: '✅', color: 'var(--c-done)' },
  failed: { label: 'Не выполнена', icon: '❌', color: 'var(--c-failed)' },
  cancelled: { label: 'Отменена', icon: '🚫', color: 'var(--c-cancel)' },
}

export const PRIORITY = {
  urgent: { label: 'Срочные', one: 'Срочная', color: 'var(--c-failed)' },
  high: { label: 'Важные', one: 'Важная', color: 'var(--c-active)' },
  normal: { label: 'Обычные', one: 'Обычная', color: 'var(--c-done)' },
}

export const KIND = {
  text: { label: 'Текст', icon: '💬' },
  photo: { label: 'Фото', icon: '📷' },
  voice: { label: 'Голосовые', icon: '🎤' },
  video: { label: 'Видео', icon: '🎥' },
  document: { label: 'Файлы', icon: '📎' },
}

export const PERIODS = [
  { days: 7, label: '7 дней' },
  { days: 30, label: '30 дней' },
  { days: 0, label: 'Всё время' },
]

export const fmtPct = (v) => (v == null ? '—' : `${v}%`)

export function fmtHours(h) {
  if (h == null) return '—'
  if (h < 1) return `${Math.max(Math.floor(h * 60), 1)} мин`
  if (h < 48) return `${h.toFixed(1)} ч`
  return `${(h / 24).toFixed(1)} дн`
}

export function fmtAge(iso, now = Date.now()) {
  const h = (now - new Date(iso).getTime()) / 3.6e6
  if (h < 1) return `${Math.max(Math.floor(h * 60), 1)} мин`
  if (h < 48) return `${Math.floor(h)} ч`
  return `${Math.floor(h / 24)} дн`
}

export function fmtDateTime(iso, tz) {
  return new Date(iso).toLocaleString('ru-RU', {
    timeZone: tz, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

export function fmtTime(iso, tz) {
  return new Date(iso).toLocaleTimeString('ru-RU', { timeZone: tz, hour: '2-digit', minute: '2-digit' })
}

// 'YYYY-MM-DD' -> '05.10' (без часовых поясов: это уже локальная дата шефа)
export const fmtDay = (d) => `${d.slice(8, 10)}.${d.slice(5, 7)}`

// plural(5, 'задача', 'задачи', 'задач') -> 'задач'
export function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}

// ---------- имена, цвета, время ----------
export function initials(name = '') {
  const words = name.trim().split(/\s+/).filter(Boolean)
  const letters = words.slice(0, 2).map((w) => Array.from(w)[0]?.toUpperCase() ?? '')
  return letters.join('') || '?'
}

// стабильный цвет аватара по id прораба
export function avatarHue(id) {
  const s = String(id)
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
  return (h * 137) % 360 // «золотой» шаг — соседние id получают заметно разные цвета
}

const dayKey = (d, tz) => d.toLocaleDateString('en-CA', { timeZone: tz })

export function fmtRel(iso, tz, now = new Date()) {
  const d = new Date(iso)
  const min = (now - d) / 6e4
  if (min < 1) return 'только что'
  if (min < 60) return `${Math.floor(min)} мин назад`
  const time = d.toLocaleTimeString('ru-RU', { timeZone: tz, hour: '2-digit', minute: '2-digit' })
  if (dayKey(d, tz) === dayKey(now, tz)) return `сегодня, ${time}`
  if (dayKey(d, tz) === dayKey(new Date(now - 864e5), tz)) return `вчера, ${time}`
  const date = d.toLocaleDateString('ru-RU', { timeZone: tz, day: '2-digit', month: '2-digit' })
  return `${date}, ${time}`
}

export function fmtClock(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '0:00'
  const s = Math.round(sec)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export const fmtSpent = (from, to) => fmtHours((new Date(to) - new Date(from)) / 3.6e6)
