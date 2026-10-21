import { memo } from 'react'
import { fmtHours, plural } from '../format.js'

export const periodText = (days) => (days === 0 ? 'за всё время' : `за ${days} дней`)

const R = 40
const C = 2 * Math.PI * R

export default memo(function Hero({ s, days, onOpenTasks }) {
  const pct = s.completion
  return (
    <section className="hero">
      <div className="hero__top">
        <div className="ring" role="img" aria-label={`Выполнение ${pct ?? 0} процентов`}>
          <svg viewBox="0 0 100 100">
            <circle cx="50" cy="50" r={R} className="ring__bg" />
            <circle
              cx="50" cy="50" r={R} className="ring__fg"
              strokeDasharray={`${(C * (pct ?? 0)) / 100} ${C}`}
              transform="rotate(-90 50 50)"
            />
          </svg>
          <div className="ring__txt">
            <b>{pct == null ? '—' : `${pct}%`}</b>
            <small>выполнено</small>
          </div>
        </div>
        <div className="hero__body">
          <div className="hero__big">{s.total}</div>
          <div className="hero__sub">{plural(s.total, 'задача отправлена', 'задачи отправлено', 'задач отправлено')} {periodText(days)}</div>
        </div>
      </div>
      <div className="hero__side">
      <div className="hero__stats">
        <span>✅ <b>{s.done}</b> выполнено</span>
        <span>❌ <b>{s.failed}</b> не выполнено</span>
        {s.cancelled > 0 && <span>🚫 <b>{s.cancelled}</b> отменено</span>}
      </div>
      <div className="tiles">
        <button className="tile" onClick={() => onOpenTasks({ status: 'new' })}>
          <span className="tile__v tile__v--warn">{s.active_now}</span>
          <span className="tile__l">в работе сейчас</span>
        </button>
        <div className="tile">
          <span className="tile__v">{fmtHours(s.avg_hours)}</span>
          <span className="tile__l">среднее время</span>
        </div>
        <div className="tile">
          <span className="tile__v">{s.foremen}</span>
          <span className="tile__l">{plural(s.foremen, 'прораб', 'прораба', 'прорабов')}</span>
        </div>
      </div>
      </div>
    </section>
  )
})
