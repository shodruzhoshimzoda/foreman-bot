import { memo, useMemo, useState } from 'react'
import { fmtDay, plural } from '../format.js'
import { useWidth } from '../hooks.js'

const SERIES = [
  ['done', 'var(--c-done)', 'Выполнено'],
  ['failed', 'var(--c-failed)', 'Не выполнено'],
  ['cancelled', 'var(--c-cancel)', 'Отменено'],
  ['active', 'var(--c-active)', 'В работе'],
]
const PAD_L = 26
const PAD_B = 20
const PAD_T = 8

export default memo(function DailyChart({ daily, chartDays, allTime }) {
  const [ref, width] = useWidth()
  const [sel, setSel] = useState(null)   // выбранный нажатием (телефон)
  const [hov, setHov] = useState(null)   // под курсором (ПК)
  const CW = Math.max((width || 348) - 28, 200) // ширина области графика: карточка минус её отступы (14px × 2)
  const H = CW > 600 ? 210 : 150
  const plotH = H - PAD_B - PAD_T
  const n = daily.length
  const max = useMemo(() => Math.max(1, ...daily.map((d) => d.total)), [daily])
  const step = (CW - PAD_L) / n
  const bw = Math.max(Math.min(step * 0.72, 30), 1)
  const active = hov ?? sel
  const day = active != null ? daily[active] : null
  const sent = daily.reduce((a, d) => a + d.total, 0)

  // подписи дат: столько, сколько помещается (первая и последняя — всегда)
  const labelIdx = useMemo(() => {
    const count = Math.min(n, Math.max(2, Math.floor((CW - PAD_L) / 70)))
    return [...new Set(Array.from({ length: count }, (_, k) => Math.round((k * (n - 1)) / Math.max(count - 1, 1))))]
  }, [n, CW])

  const yOf = (v) => PAD_T + plotH - (v / max) * plotH
  const ticks = [...new Set([0, Math.round(max / 2), max])]

  return (
    <section>
      <h2>Отправлено по дням{allTime ? ` · последние ${chartDays}` : ''}</h2>
      <div className="card" ref={ref}>
        <svg
          width={CW} height={H} viewBox={`0 0 ${CW} ${H}`}
          className={`chart ${active != null ? 'has-sel' : ''}`}
          role="img" aria-label={`Задачи по дням, всего ${sent}`}
          onMouseLeave={() => setHov(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD_L} x2={CW} y1={yOf(t)} y2={yOf(t)} className="grid-line" />
              <text x={PAD_L - 6} y={yOf(t) + 3.5} className="axis" textAnchor="end">{t}</text>
            </g>
          ))}
          {daily.map((d, i) => {
            let y = PAD_T + plotH
            const x = PAD_L + i * step + (step - bw) / 2
            return (
              <g key={d.date} className={active === i ? 'bar sel' : 'bar'}
                onClick={() => setSel(sel === i ? null : i)} onMouseEnter={() => setHov(i)}>
                <rect x={PAD_L + i * step} y={PAD_T} width={step} height={plotH} fill="transparent" />
                {SERIES.map(([k, color]) => {
                  const h = (d[k] / max) * plotH
                  if (!h) return null
                  y -= h
                  return <rect key={k} x={x} y={y} width={bw} height={Math.max(h - 0.6, 0.6)} fill={color} rx={bw > 5 ? 2 : 0} />
                })}
              </g>
            )
          })}
          {labelIdx.map((i) => {
            const cx = PAD_L + i * step + step / 2
            const anchor = i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'
            return <text key={i} x={anchor === 'start' ? PAD_L : anchor === 'end' ? CW : cx} y={H - 5} className="axis" textAnchor={anchor}>{fmtDay(daily[i].date)}</text>
          })}
        </svg>
        <div className="legend">
          {day ? (
            <strong>{fmtDay(day.date)}: {day.total} {plural(day.total, 'задача', 'задачи', 'задач')}
              {SERIES.filter(([k]) => day[k]).map(([k, , label]) => ` · ${label.toLowerCase()} ${day[k]}`)}</strong>
          ) : (
            SERIES.map(([k, color, label]) => (
              <span key={k}><i style={{ background: color }} />{label}</span>
            ))
          )}
        </div>
      </div>
    </section>
  )
})
