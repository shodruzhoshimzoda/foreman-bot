import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, fetchDashboard, setTaskStatus, tg } from './api.js'
import { PERIODS, fmtTime } from './format.js'
import Overview from './components/Overview.jsx'
import Team from './components/Team.jsx'
import TasksTab from './components/TasksTab.jsx'
import Sidebar from './components/Sidebar.jsx'
import { Lightbox, LightboxContext } from './components/Media.jsx'
import { TaskActions, TaskPanelContext } from './components/actions.jsx'
import TaskPanel from './components/TaskPanel.jsx'
import Toast from './components/Toast.jsx'

const REFRESH_MS = 30_000
const TITLES = { overview: 'Обзор', team: 'Прорабы', tasks: 'Задачи' }
const MESSAGES = {
  done: (t) => `✅ Задача #${t.id} · ${t.foreman} — выполнена`,
  failed: (t) => `❌ Задача #${t.id} · ${t.foreman} — не выполнена`,
  cancelled: (t) => `🚫 Задача #${t.id} · ${t.foreman} — отменена`,
  new: (t) => `↩ Задача #${t.id} снова в работе`,
}

function Problem({ error, onRetry }) {
  const map = {
    401: ['📱', 'Откройте из Telegram', 'Дашборд работает только внутри бота — нажмите кнопку «📊 Дашборд».'],
    403: ['🔒', 'Только для шефа', 'У вашего аккаунта нет доступа к этой панели.'],
  }
  const [icon, title, text] = map[error.status] || [
    '⚠️', 'Не удалось загрузить', error.status === 0 ? 'Нет связи с сервером.' : 'Сервер вернул ошибку. Попробуйте ещё раз.',
  ]
  return (
    <div className="problem">
      <div className="problem__icon">{icon}</div>
      <h2>{title}</h2>
      <p>{text}</p>
      {error.status !== 401 && error.status !== 403 && <button onClick={onRetry}>Повторить</button>}
    </div>
  )
}

const Skeleton = () => (
  <div aria-busy="true">
    <div className="sk sk--hero" />
    <div className="sk sk--chart" />
    <div className="sk sk--card" />
  </div>
)

export default function App() {
  const [tab, setTab] = useState('overview')
  const [visited, setVisited] = useState({ overview: true })
  const [days, setDays] = useState(7)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState({ status: '', foreman: '' })
  const [refreshKey, setRefreshKey] = useState(0)
  const [photo, setPhoto] = useState(null)
  const [overrides, setOverrides] = useState({})   // отметки результата, сделанные в этом сеансе
  const [busy, setBusy] = useState(() => new Set()) // задачи, для которых запрос ещё идёт
  const [toast, setToast] = useState(null)
  const [panel, setPanel] = useState(null)         // открытая панель задачи
  const cache = useRef(new Map())   // период -> последние данные: переключение мгновенное
  const abort = useRef(null)

  const load = useCallback(async (period, { silent = false } = {}) => {
    abort.current?.abort()
    const ctl = (abort.current = new AbortController())
    if (!silent) setLoading(true)
    try {
      const next = await fetchDashboard(period, ctl.signal)
      cache.current.set(period, next)
      setData(next)
      setError(null)
    } catch (e) {
      if (e.name === 'AbortError') return
      if (!silent || !cache.current.has(period)) setError(e instanceof ApiError ? e : new ApiError(0, String(e)))
    } finally {
      if (abort.current === ctl) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const cached = cache.current.get(days)
    if (cached) setData(cached)
    load(days, { silent: !!cached })
  }, [days, load])

  useEffect(() => {
    const tick = () => document.visibilityState === 'visible' && load(days, { silent: true })
    const id = setInterval(tick, REFRESH_MS)
    document.addEventListener('visibilitychange', tick)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [days, load])

  // ---- отметка результата: ✅ / ❌ / 🚫 и «вернуть в работу»
  const daysRef = useRef(days)
  daysRef.current = days
  const actRef = useRef(null)
  const act = useCallback(async (task, to) => {
    const note = (kind, text, undo) => setToast({ id: Date.now(), kind, text, undo })
    setBusy((b) => new Set(b).add(task.id))
    try {
      const { task: u } = await setTaskStatus(task.id, to)
      setOverrides((o) => ({ ...o, [task.id]: { status: u.status, closed_at: u.closed_at } }))
      tg?.HapticFeedback?.notificationOccurred?.(to === 'failed' ? 'warning' : 'success')
      note('ok', MESSAGES[to](task), to === 'new' ? null : () => actRef.current(task, 'new'))
      load(daysRef.current, { silent: true }) // обновить цифры на «Обзоре» и «Прорабах»
    } catch (e) {
      if (e.status === 409 && e.data?.task) {
        // задачу уже закрыли в другом месте (например, в боте) — показываем актуальное состояние
        const u = e.data.task
        setOverrides((o) => ({ ...o, [task.id]: { status: u.status, closed_at: u.closed_at } }))
        note('err', 'Статус этой задачи уже изменён — показано актуальное состояние.')
        load(daysRef.current, { silent: true })
      } else if (e.status === 401 || e.status === 403) {
        note('err', 'Нет доступа. Откройте дашборд заново из бота.')
      } else {
        tg?.HapticFeedback?.notificationOccurred?.('error')
        note('err', 'Не удалось сохранить. Проверьте соединение и повторите.')
      }
    } finally {
      setBusy((b) => {
        const n = new Set(b)
        n.delete(task.id)
        return n
      })
    }
  }, [load])
  actRef.current = act
  const actions = useMemo(() => ({ overrides, busy, act }), [overrides, busy, act])
  const closeToast = useCallback(() => setToast(null), [])

  const go = useCallback((next) => {
    tg?.HapticFeedback?.selectionChanged()
    setTab(next)
    setVisited((v) => (v[next] ? v : { ...v, [next]: true }))
    window.scrollTo({ top: 0 })
  }, [])

  const openTasks = useCallback((f = {}) => {
    setFilter({ status: f.status || '', foreman: f.foreman || '' })
    go('tasks')
  }, [go])

  const panelToForeman = useCallback((foreman) => {
    setPanel(null)
    openTasks({ foreman })
  }, [openTasks])

  const pickPeriod = (d) => {
    if (d === days) return
    tg?.HapticFeedback?.selectionChanged()
    setData(cache.current.get(d) ?? null)
    setError(null)
    setDays(d)
  }

  const refresh = useCallback(
    () => (tab === 'tasks' ? setRefreshKey((k) => k + 1) : load(days)),
    [tab, days, load],
  )
  const closePhoto = useCallback(() => setPhoto(null), [])
  const closePanel = useCallback(() => setPanel(null), [])
  const openPanel = useCallback((t) => setPanel(t), [])
  const openPhoto = useCallback((media, index = 0) => setPhoto({ media, index }), [])
  const fatal = error && !data

  // «На весь экран» (Bot API 8.0+; в Telegram Desktop — развернуть окно приложения)
  const [isFs, setIsFs] = useState(!!tg?.isFullscreen)
  useEffect(() => {
    const on = () => setIsFs(!!tg.isFullscreen)
    tg?.onEvent?.('fullscreenChanged', on)
    return () => tg?.offEvent?.('fullscreenChanged', on)
  }, [])
  const fullscreen = {
    can: !!tg?.requestFullscreen && !!tg?.isVersionAtLeast?.('8.0'),
    on: isFs,
    toggle: () => (isFs ? tg.exitFullscreen() : tg.requestFullscreen()),
  }

  // горячие клавиши для ноутбука: 1/2/3 — разделы, R — обновить
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || photo || panel) return
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return
      const k = e.key.toLowerCase()
      if (k === '1') go('overview')
      else if (k === '2') go('team')
      else if (k === '3') go('tasks')
      else if (k === 'r' || k === 'к') refresh()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [go, refresh, photo, panel])

  const periodTab = tab === 'overview' || tab === 'team'

  return (
    <LightboxContext.Provider value={openPhoto}>
      <TaskActions.Provider value={actions}>
      <TaskPanelContext.Provider value={openPanel}>
      <div className={`shell ${fatal ? 'shell--solo' : ''}`}>
        {!fatal && <Sidebar tab={tab} onChange={go} badge={data?.summary.active_now ?? 0} fullscreen={fullscreen} />}

        <main className="content">
          <header className="top">
            <div className="top__title">
              <h1>{TITLES[tab]}</h1>
              <div className="muted" aria-live="polite">
                {data ? `Обновлено в ${fmtTime(data.generated_at, data.tz)}` : 'Загрузка…'}
              </div>
            </div>
            {periodTab && (
              <div className="seg top__seg" role="tablist" aria-label="Период">
                {PERIODS.map((p) => (
                  <button key={p.days} role="tab" aria-selected={p.days === days} className={p.days === days ? 'on' : ''} onClick={() => pickPeriod(p.days)}>
                    {p.label}
                  </button>
                ))}
              </div>
            )}
            <button className="icon-btn top__refresh" onClick={refresh} disabled={loading && tab !== 'tasks'} aria-label="Обновить" title="Обновить (R)">
              <span className={loading && tab !== 'tasks' ? 'spin' : ''}>↻</span>
            </button>
          </header>

          {fatal ? (
            <Problem error={error} onRetry={() => load(days)} />
          ) : !data ? (
            <Skeleton />
          ) : (
            <>
              <div data-tab="overview" hidden={tab !== 'overview'} className={loading ? 'dim' : ''}>
                <Overview data={data} onOpenTasks={openTasks} />
              </div>
              <div data-tab="team" hidden={tab !== 'team'} className={loading ? 'dim' : ''}>
                <Team foremen={data.foremen} onOpenTasks={openTasks} />
              </div>
              {visited.tasks && (
                <div data-tab="tasks" hidden={tab !== 'tasks'}>
                  <TasksTab filter={filter} setFilter={setFilter} foremen={data.foremen} tz={data.tz} refreshKey={refreshKey} />
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {panel && data && <TaskPanel task={panel} tz={data.tz} onClose={closePanel} onForeman={panelToForeman} />}
      {photo && <Lightbox media={photo.media} index={photo.index} onClose={closePhoto} />}
      <Toast toast={toast} onClose={closeToast} />
      </TaskPanelContext.Provider>
      </TaskActions.Provider>
    </LightboxContext.Provider>
  )
}
