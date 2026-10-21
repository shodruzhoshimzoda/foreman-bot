import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, fetchTasks } from '../api.js'
import TaskList from './TaskList.jsx'
import { useTaskActions } from './actions.jsx'

const FILTERS = [
  ['', 'Все'],
  ['new', '🔧 В работе'],
  ['done', '✅ Выполнены'],
  ['failed', '❌ Не выполнены'],
  ['cancelled', '🚫 Отменены'],
]

export default function TasksTab({ filter, setFilter, foremen, tz, refreshKey }) {
  const [items, setItems] = useState([])
  const [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const { overrides } = useTaskActions()
  const ctl = useRef(null)
  const sentinel = useRef(null)
  const state = useRef({})
  state.current = { next, loading, filter }

  const load = useCallback(async (reset) => {
    const { next: before, filter: f } = state.current
    ctl.current?.abort()
    const c = (ctl.current = new AbortController())
    setLoading(true)
    setError(null)
    try {
      const page = await fetchTasks({ status: f.status, foreman: f.foreman, before: reset ? undefined : before }, c.signal)
      setItems((prev) => (reset ? page.tasks : [...prev, ...page.tasks]))
      setNext(page.next)
    } catch (e) {
      if (e.name === 'AbortError') return
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)))
    } finally {
      if (ctl.current === c) setLoading(false)
    }
  }, [])

  // фильтры или «обновить» → список с начала
  useEffect(() => {
    setItems([])
    setNext(null)
    state.current.next = null
    load(true)
    return () => ctl.current?.abort()
  }, [filter.status, filter.foreman, refreshKey, load])

  // подгрузка при прокрутке до конца списка
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const io = new IntersectionObserver(
      ([e]) => e.isIntersecting && state.current.next && !state.current.loading && load(false),
      { rootMargin: '400px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [load, items.length])

  // при фильтре по статусу закрытая в этом сеансе задача уходит из списка (а «Вернуть» — возвращает её)
  const visible = filter.status
    ? items.filter((t) => !overrides[t.id] || overrides[t.id].status === filter.status)
    : items

  return (
    <>
      <div className="filters">
        <div className="filters__chips" role="tablist">
          <select
            className={`fchip fchip--select ${filter.foreman ? 'on' : ''}`}
            value={filter.foreman || ''}
            onChange={(e) => setFilter({ ...filter, foreman: e.target.value ? Number(e.target.value) : '' })}
            aria-label="Прораб"
          >
            <option value="">👷 Все прорабы</option>
            {foremen.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
          {FILTERS.map(([key, label]) => (
            <button key={key} role="tab" aria-selected={(filter.status || '') === key}
              className={`fchip ${(filter.status || '') === key ? 'on' : ''}`}
              onClick={() => setFilter({ ...filter, status: key })}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <TaskList tz={tz} tasks={visible} />

      {error && (
        <div className="problem problem--inline">
          <p>{error.status === 0 ? 'Нет связи с сервером.' : 'Не удалось загрузить задачи.'}</p>
          <button onClick={() => load(items.length === 0)}>Повторить</button>
        </div>
      )}
      {loading && <div className="sk sk--card" aria-busy="true" />}
      {!loading && !error && visible.length === 0 && <p className="empty">Задач с такими условиями нет.</p>}
      {!loading && next && <button className="btn btn--soft" onClick={() => load(false)}>Показать ещё</button>}
      <div ref={sentinel} style={{ height: 1 }} />
    </>
  )
}
