import { STATUS } from '../format.js'
import { useTaskActions } from './actions.jsx'

// ✅ / ❌ / 🚫 для задачи «в работе»; для закрытой — статус и «Вернуть в работу».
export default function ActionButtons({ t, size = 'lg', showStatus = true }) {
  const { act, busy } = useTaskActions()
  const disabled = busy.has(t.id)
  const st = STATUS[t.status]

  if (t.status !== 'new') {
    return (
      <div className={`acts acts--closed acts--${size}`}>
        {showStatus && <span className="badge" style={{ '--bc': st.color }}>{st.icon} {st.label}</span>}
        <button className="act act--undo" disabled={disabled} onClick={() => act(t, 'new')}>↩ Вернуть в работу</button>
      </div>
    )
  }
  return (
    <div className={`acts acts--${size}`}>
      <button className="act act--done" disabled={disabled} onClick={() => act(t, 'done')}>
        <span aria-hidden="true">✅</span> Выполнено
      </button>
      <button className="act act--fail" disabled={disabled} onClick={() => act(t, 'failed')}>
        <span aria-hidden="true">❌</span> Не выполнено
      </button>
      <button className="act act--cancel" disabled={disabled} onClick={() => act(t, 'cancelled')}
        title="Отменить задачу (например, отправлена по ошибке)" aria-label="Отменить задачу">🚫</button>
    </div>
  )
}
