import { memo } from 'react'
import { KIND, PRIORITY } from '../format.js'

function Bars({ title, items, total }) {
  return (
    <div className="card">
      <div className="muted">{title}</div>
      {items.map(([key, label, value, color]) => (
        <div className="hbar" key={key}>
          <div className="hbar__label">{label}</div>
          <div className="hbar__track"><span style={{ width: total ? `${(value / total) * 100}%` : 0, background: color }} /></div>
          <div className="hbar__value">{value}</div>
        </div>
      ))}
    </div>
  )
}

export default memo(function Breakdown({ byKind, byPriority, total }) {
  if (!total) return null
  return (
    <section>
      <h2>Как отправлялись задачи</h2>
      <div className="breakdown">
      <Bars
        title="По важности"
        total={total}
        items={Object.entries(PRIORITY).map(([k, p]) => [k, p.label, byPriority[k], p.color])}
      />
      <Bars
        title="По типу сообщения"
        total={total}
        items={Object.entries(KIND).filter(([k]) => byKind[k] > 0).map(([k, v]) => [k, `${v.icon} ${v.label}`, byKind[k], 'var(--c-accent)'])}
      />
      </div>
    </section>
  )
})
