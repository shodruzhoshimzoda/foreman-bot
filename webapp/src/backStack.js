import { useEffect, useRef } from 'react'
import { tg } from './api.js'

// Стек «слоёв» (панель задачи, просмотр фото…): кнопка «назад» Telegram и клавиша Esc закрывают только верхний.
const stack = []
let bound = false

function dispatch() {
  stack.at(-1)?.()
}

if (typeof document !== 'undefined') {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && stack.length) {
      e.preventDefault()
      dispatch()
    }
  })
}

export function pushLayer(fn) {
  stack.push(fn)
  const bb = tg?.BackButton
  if (bb) {
    if (!bound) {
      bb.onClick(dispatch)
      bound = true
    }
    bb.show()
  }
  return () => {
    const i = stack.lastIndexOf(fn)
    if (i >= 0) stack.splice(i, 1)
    if (!stack.length) tg?.BackButton?.hide()
  }
}

export const hasLayers = () => stack.length > 0

// Пока компонент на экране, он — верхний слой: Esc и «назад» вызывают onClose.
export function useLayer(onClose) {
  const ref = useRef(onClose)
  ref.current = onClose
  useEffect(() => pushLayer(() => ref.current()), [])
}
