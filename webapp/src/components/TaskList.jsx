import { DESKTOP, useMedia } from '../hooks.js'
import TaskCard from './TaskCard.jsx'
import TaskRow from './TaskRow.jsx'

// Телефон и узкое окно — карточки в одну колонку; ноутбук и ПК — упорядоченная таблица строк.
export default function TaskList({ tasks, tz }) {
  const desktop = useMedia(DESKTOP)
  if (!tasks.length) return null
  if (!desktop) {
    return <div className="cards">{tasks.map((t) => <TaskCard key={t.id} t={t} tz={tz} />)}</div>
  }
  return (
    <div className="tlist" role="list">
      <div className="tlist__head" aria-hidden="true">
        <span>Прораб</span>
        <span>Задача</span>
        <span>Результат</span>
      </div>
      {tasks.map((t) => <TaskRow key={t.id} t={t} tz={tz} />)}
    </div>
  )
}
