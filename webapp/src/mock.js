// Тестовые данные для `npm run dev:mock` — интерфейс можно дорабатывать без бота и Telegram.
const rnd = (seed) => () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646
const NAMES = ['Иванов Алишер', 'Петров Сергей', 'Каримов Рустам', 'Назаров Фарход', 'Сафаров Умед']
const KINDS = ['text', 'photo', 'voice', 'video', 'document']
const PRIOS = ['urgent', 'high', 'normal']
const STATUSES = ['new', 'done', 'done', 'failed', 'cancelled', 'new']
const TEXTS = ['Залить фундамент на втором участке до пятницы', 'Проверить армирование', '', 'Принять бетон, 12 кубов. Фото накладной прислать шефу.', 'Закрыть сметы по блоку Б']

const LONG = 'Залить фундамент на втором участке до пятницы.\n\nПеред заливкой:\n— проверить армирование и опалубку;\n— принять бетон (12 кубов), накладную сфотографировать;\n— после заливки накрыть плёнкой и записать голосовое: как прошло.\n\n' + 'Если что-то пойдёт не так — сразу звонить мне, не ждать вечера. '.repeat(8)

// картинка-заглушка (SVG) — вместо настоящего фото
const EMOJI = ['🧱', '🏗️', '🪜', '🧰', '📐', '🪵', '🚧', '⛑️']
const photo = (i) => {
  const h = (i * 47) % 360
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="560"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${h},55%,60%)"/><stop offset="1" stop-color="hsl(${(h + 50) % 360},60%,38%)"/></linearGradient></defs><rect width="800" height="560" fill="url(#g)"/><text x="400" y="320" font-size="150" text-anchor="middle">${EMOJI[i % EMOJI.length]}</text></svg>`
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg)
}

// короткий «тон» в формате WAV — чтобы проверить плеер голосовых
function tone(seconds = 4) {
  const rate = 8000, n = rate * seconds
  const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf)
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVEfmt '); v.setUint32(16, 16, true)
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true)
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true)
  for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.sin((i / rate) * 2 * Math.PI * (330 + (i / n) * 220)) * 3000, true)
  let bin = ''
  new Uint8Array(buf).forEach((b) => (bin += String.fromCharCode(b)))
  return 'data:audio/wav;base64,' + btoa(bin)
}
let VOICE
const now = Date.now()

// k → число вложений: задачи-альбомы (одна из них — фото вместе с видео)
const ALBUMS = { 2: 3, 5: 6, 8: 2, 12: 4 }

function mkTask(id, k) {
  let kind = KINDS[[0, 1, 2, 1, 0, 2, 3][k % 7]]
  const status = STATUSES[k % 6]
  const created = now - (k + 1) * 3.1e6 - (k > 8 ? k * 2e7 : 0)
  const f = NAMES[k % 5]
  let media = kind === 'photo' ? { url: photo(k), duration: null, items: null } : kind === 'voice' ? { url: (VOICE ||= tone()), duration: 4 + (k % 9), items: null } : null
  let album = 0
  if (ALBUMS[k]) {
    album = ALBUMS[k]
    kind = 'photo'
    const kinds = Array.from({ length: album }, (_, j) => (k === 12 && j === 1 ? 'video' : 'photo'))
    const srcs = kinds.map((_, j) => photo(k * 10 + j))
    media = { url: srcs[0], srcs, duration: null, items: kinds.map((x) => ({ kind: x })) }
  }
  return {
    id, foreman_id: (k % 5) + 1, foreman: f, kind, priority: PRIOS[k % 3], status, album,
    text: k === 5 ? LONG : kind === 'text' ? TEXTS[(k % 4) + (k % 4 === 2 ? 1 : 0)] : k % 3 === 0 && !album ? '' : TEXTS[k % 5],
    created_at: new Date(created).toISOString(),
    closed_at: status === 'new' ? null : new Date(created + (1 + (k % 7)) * 1.9e6).toISOString(),
    media,
  }
}
const ALL = Array.from({ length: 64 }, (_, k) => mkTask(200 - k, k))


// в списках текст сжат в одну строку и обрезан (как на сервере)
const listView = (t) => {
  const flat = t.text.split(/\s+/).join(' ')
  return { ...t, text: flat.length > 600 ? flat.slice(0, 600) + '…' : flat }
}

export function mockTask(id) {
  const t = ALL.find((x) => x.id === id)
  if (!t) throw Object.assign(new Error('not found'), { status: 404 })
  return { task: { ...t } }
}

export function mockSetStatus(id, status) {
  const t = ALL.find((x) => x.id === id)
  const closing = status !== 'new'
  if (closing === (t.status !== 'new')) throw Object.assign(new Error('conflict'), { status: 409, data: { task: t } })
  t.status = status
  t.closed_at = closing ? new Date().toISOString() : null
  return { task: { ...t } }
}

export function mockTasks({ status, foreman, before }) {
  let list = ALL.filter((t) => (!status || t.status === status) && (!foreman || t.foreman_id === Number(foreman)) && (!before || t.id < before))
  const page = list.slice(0, 20)
  return { tasks: page.map(listView), next: list.length > 20 ? page.at(-1).id : null }
}

export function mockDashboard(days) {
  const r = rnd(days + 7)
  const scale = days === 0 ? 4 : days === 30 ? 2 : 1
  const foremen = NAMES.map((name, i) => {
    const done = Math.floor((8 - i) * scale + r() * 3), failed = Math.floor(r() * 3 * scale)
    const cancelled = Math.floor(r() * 2), active = Math.floor(r() * 4)
    const total = done + failed + cancelled + active
    const k = Object.fromEntries(KINDS.map((x) => [x, 0])), p = { urgent: 0, high: 0, normal: 0 }
    for (let n = 0; n < total; n++) { k[KINDS[Math.floor(r() * 3.4)]]++; p[PRIOS[Math.floor(r() * r() * 3)]]++ }
    return { id: i + 1, name, total, done, failed, cancelled, active,
      completion: done + failed ? Math.round((done / (done + failed)) * 100) : null,
      avg_hours: done ? 1 + r() * 30 : null, priority: p, kinds: k }
  })
  const sum = (key) => foremen.reduce((a, f) => a + f[key], 0)
  const n = Math.min(days || 90, 90), today = new Date()
  const daily = Array.from({ length: n }, (_, i) => {
    const d = new Date(today); d.setDate(d.getDate() - (n - 1 - i))
    const total = Math.floor(r() * 7), done = Math.floor(total * 0.6), failed = Math.floor((total - done) / 2)
    return { date: d.toISOString().slice(0, 10), total, done, failed, cancelled: 0, active: total - done - failed }
  })
  const totals = ['total', 'done', 'failed', 'cancelled', 'active'].reduce((a, k) => ({ ...a, [k]: sum(k) }), {})
  return {
    tz: 'Asia/Dushanbe', days, generated_at: new Date().toISOString(), media_enabled: true,
    summary: { ...totals, completion: Math.round((sum('done') / Math.max(sum('done') + sum('failed'), 1)) * 100), avg_hours: 14.2, foremen: foremen.length, active_now: ALL.filter((t) => t.status === 'new').length },
    by_priority: Object.fromEntries(PRIOS.map((p) => [p, foremen.reduce((a, f) => a + f.priority[p], 0)])),
    by_kind: Object.fromEntries(KINDS.map((k) => [k, foremen.reduce((a, f) => a + f.kinds[k], 0)])),
    foremen, daily, daily_days: n,
    recent: ALL.slice(0, 6).map(listView),
    stale: ALL.filter((t) => t.status === 'new').slice(-3).reverse().map(listView),
  }
}
