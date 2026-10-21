import { useEffect } from 'react'

export default function Toast({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(onClose, toast.kind === 'err' ? 4500 : 7000)
    return () => clearTimeout(id)
  }, [toast, onClose])

  if (!toast) return null
  return (
    <div className={`toast toast--${toast.kind}`} role="status" key={toast.id}>
      <span>{toast.text}</span>
      {toast.undo && (
        <button onClick={() => { toast.undo(); onClose() }}>Вернуть в работу</button>
      )}
      <button className="toast__x" onClick={onClose} aria-label="Закрыть">✕</button>
    </div>
  )
}
