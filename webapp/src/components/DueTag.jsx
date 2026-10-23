import { dueInfo } from '../format.js'

// «⏰ до 25.10, 14:51» — у просроченной задачи в работе красным
export default function DueTag({ t, tz }) {
  const due = dueInfo(t, tz)
  if (!due) return null
  return <span className={`tag ${due.late ? 'tag--late' : 'tag--due'}`}>{due.late ? '🔥 просрочена · ' : '⏰ '}{due.text}</span>
}
