// Принял ли прораб задачу: «👍 принял» / «👀 не принял» (только пока задача в работе)
export default function AcceptTag({ t }) {
  if (t.status === 'new') {
    return t.accepted_at
      ? <span className="tag tag--ok">👍 принял</span>
      : <span className="tag tag--seen">👀 не принял</span>
  }
  return null
}
