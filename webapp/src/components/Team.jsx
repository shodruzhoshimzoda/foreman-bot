import { memo, useMemo, useState } from 'react'
import { KIND, PRIORITY, fmtHours, fmtPct, plural } from '../format.js'
import Avatar from './Avatar.jsx'
import { DESKTOP, useMedia } from '../hooks.js'

function Bar({ f }) {
  const t = Math.max(f.total, 1)
  const parts = [['done', f.done], ['failed', f.failed], ['cancel', f.cancelled], ['active', f.active]]
  return (
    <div className="stack" aria-hidden="true">
      {parts.map(([k, v]) => v > 0 && <span key={k} style={{ width: `${(v / t) * 100}%`, background: `var(--c-${k})` }} />)}
    </div>
  )
}

const Row = memo(function Row({ f, open, onToggle, onOpenTasks }) {
  const tone = f.completion == null ? '' : f.completion >= 80 ? 'good' : f.completion >= 50 ? 'mid' : 'bad'
  return (
    <div className="card foreman">
      <button className="foreman__head" onClick={onToggle} aria-expanded={open}>
        <Avatar id={f.id} name={f.name} size={44} />
        <div className="foreman__who">
          <b>{f.name}</b>
          <span className="muted">
            {f.total} {plural(f.total, 'задача', 'задачи', 'задач')}
            {f.active > 0 && ` · ${f.active} в работе`}
          </span>
        </div>
        <span className={`pill ${tone && 'pill--' + tone}`}>{fmtPct(f.completion)}</span>
        <span className={`caret ${open ? 'open' : ''}`}>›</span>
      </button>

      {f.total === 0 ? (
        <div className="muted foreman__none">За период задач не было</div>
      ) : (
        <>
          <Bar f={f} />
          <div className="foreman__nums">
            <span>✅ {f.done}</span><span>❌ {f.failed}</span><span>🔧 {f.active}</span>
            {f.cancelled > 0 && <span>🚫 {f.cancelled}</span>}
            <span className="push">⏱ {fmtHours(f.avg_hours)}</span>
          </div>
        </>
      )}

      {open && f.total > 0 && (
        <div className="foreman__more">
          <div className="muted">Важность</div>
          <div className="chips">
            {Object.entries(PRIORITY).map(([k, p]) => (
              <span key={k} className="chip"><i className="dot" style={{ background: p.color }} />{p.label} {f.priority[k]}</span>
            ))}
          </div>
          <div className="muted">Как отправлено</div>
          <div className="chips">
            {Object.entries(KIND).filter(([k]) => f.kinds[k] > 0).map(([k, v]) => (
              <span key={k} className="chip">{v.icon} {v.label} {f.kinds[k]}</span>
            ))}
          </div>
        </div>
      )}
      {open && <button className="btn btn--soft" onClick={() => onOpenTasks({ foreman: f.id })}>Задачи прораба →</button>}
    </div>
  )
})

// ---------- таблица для ноутбука и ПК ----------
const COLS = [
  ['name', 'Прораб', 'left'],
  ['total', 'Задач', 'num'],
  ['done', '✅', 'num'],
  ['failed', '❌', 'num'],
  ['active', '🔧', 'num'],
  ['cancelled', '🚫', 'num'],
  ['completion', 'Выполнение', 'rate'],
  ['avg_hours', 'Ср. время', 'num'],
]

function sortValue(f, key) {
  const v = f[key]
  return key === 'name' ? v.toLocaleLowerCase('ru') : v
}

function Table({ foremen, onOpenTasks }) {
  const [sort, setSort] = useState({ key: 'total', dir: 'desc' })

  const rows = useMemo(() => {
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...foremen].sort((a, b) => {
      const x = sortValue(a, sort.key), y = sortValue(b, sort.key)
      if (x == null && y == null) return 0
      if (x == null) return 1            // пустые значения всегда внизу
      if (y == null) return -1
      return (typeof x === 'string' ? x.localeCompare(y, 'ru') : x - y) * dir
    })
  }, [foremen, sort])

  const total = useMemo(() => {
    const sum = (k) => foremen.reduce((a, f) => a + f[k], 0)
    const done = sum('done'), failed = sum('failed')
    const w = foremen.filter((f) => f.avg_hours != null)
    const wd = w.reduce((a, f) => a + f.done, 0)
    return {
      total: sum('total'), done, failed, active: sum('active'), cancelled: sum('cancelled'),
      completion: done + failed ? Math.round((done / (done + failed)) * 100) : null,
      avg_hours: wd ? w.reduce((a, f) => a + f.avg_hours * f.done, 0) / wd : null,
      priority: ['urgent', 'high', 'normal'].map((p) => foremen.reduce((a, f) => a + f.priority[p], 0)),
      kinds: Object.fromEntries(Object.keys(KIND).map((k) => [k, foremen.reduce((a, f) => a + f.kinds[k], 0)])),
    }
  }, [foremen])

  const toggle = (key) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'name' ? 'asc' : 'desc' }))

  const Prio = ({ p }) => (
    <span className="mix">
      {Object.entries(PRIORITY).map(([k, v], i) => (
        <span key={k} title={v.label}><i className="dot" style={{ background: v.color }} />{Array.isArray(p) ? p[i] : p[k]}</span>
      ))}
    </span>
  )
  const Kinds = ({ k }) => (
    <span className="mix">
      {Object.entries(KIND).filter(([key]) => k[key] > 0).map(([key, v]) => (
        <span key={key} title={v.label}>{v.icon} {k[key]}</span>
      ))}
    </span>
  )

  return (
    <div className="card table-card">
      <table className="table">
        <thead>
          <tr>
            {COLS.map(([key, label, kind]) => (
              <th key={key} className={`t-${kind}`} aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <button onClick={() => toggle(key)}>
                  {label}<span className="sort">{sort.key === key ? (sort.dir === 'asc' ? '▲' : '▼') : ''}</span>
                </button>
              </th>
            ))}
            <th className="t-left col-prio">Важность</th>
            <th className="t-left col-mix">Как отправлено</th>
            <th aria-hidden="true" />
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => {
            const tone = f.completion == null ? '' : f.completion >= 80 ? 'good' : f.completion >= 50 ? 'mid' : 'bad'
            return (
              <tr key={f.id} tabIndex={0} onClick={() => onOpenTasks({ foreman: f.id })}
                onKeyDown={(e) => e.key === 'Enter' && onOpenTasks({ foreman: f.id })} title="Открыть задачи прораба">
                <td className="t-left">
                  <div className="who">
                    <Avatar id={f.id} name={f.name} size={36} />
                    <div><b>{f.name}</b><span className="muted">{f.active > 0 ? `${f.active} в работе` : 'нет активных'}</span></div>
                  </div>
                </td>
                <td className="t-num"><b>{f.total}</b></td>
                <td className="t-num">{f.done}</td>
                <td className="t-num">{f.failed}</td>
                <td className="t-num">{f.active}</td>
                <td className="t-num">{f.cancelled}</td>
                <td className="t-rate">
                  <div className="rate"><span className={`pill ${tone && 'pill--' + tone}`}>{fmtPct(f.completion)}</span><Bar f={f} /></div>
                </td>
                <td className="t-num">{fmtHours(f.avg_hours)}</td>
                <td className="t-left col-prio"><Prio p={f.priority} /></td>
                <td className="t-left col-mix"><Kinds k={f.kinds} /></td>
                <td className="t-go" aria-hidden="true">›</td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <td className="t-left"><b>Итого</b></td>
            <td className="t-num"><b>{total.total}</b></td>
            <td className="t-num">{total.done}</td>
            <td className="t-num">{total.failed}</td>
            <td className="t-num">{total.active}</td>
            <td className="t-num">{total.cancelled}</td>
            <td className="t-rate"><b>{fmtPct(total.completion)}</b></td>
            <td className="t-num">{fmtHours(total.avg_hours)}</td>
            <td className="t-left col-prio"><Prio p={total.priority} /></td>
            <td className="t-left col-mix"><Kinds k={total.kinds} /></td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

export default memo(function Team({ foremen, onOpenTasks }) {
  const desktop = useMedia(DESKTOP)
  const [open, setOpen] = useState(null)
  if (!foremen.length) {
    return <p className="empty">Прорабов пока нет. Отправьте им ссылку-приглашение в боте («👷 Прорабы»).</p>
  }
  if (desktop) return <Table foremen={foremen} onOpenTasks={onOpenTasks} />
  return (
    <section>
      {foremen.map((f) => (
        <Row key={f.id} f={f} open={open === f.id} onToggle={() => setOpen(open === f.id ? null : f.id)} onOpenTasks={onOpenTasks} />
      ))}
    </section>
  )
})
