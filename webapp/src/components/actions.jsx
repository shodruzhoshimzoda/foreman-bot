import { createContext, useContext } from 'react'

// Отметки результата, сделанные в этом сеансе: { [id задачи]: { status, closed_at } }.
// Карточки и строки накладывают их поверх данных списка — статус меняется сразу, без перезагрузки.
export const TaskActions = createContext({ overrides: {}, busy: new Set(), act: () => {} })

export const useTaskActions = () => useContext(TaskActions)

export function useTaskView(t) {
  const { overrides } = useContext(TaskActions)
  const o = overrides[t.id]
  return o ? { ...t, ...o } : t
}

// Открыть панель задачи
export const TaskPanelContext = createContext(() => {})

// Клик по карточке/строке открывает панель; кнопки, плеер, фото и выделение текста — не открывают.
const INTERACTIVE = 'button, a, audio, select, input, .voice, .ptile, .pgrid'

export function openProps(open, t) {
  return {
    tabIndex: 0,
    'aria-label': `Открыть задачу #${t.id}`,
    onClick: (e) => {
      if (e.target.closest(INTERACTIVE) || window.getSelection()?.toString()) return
      open(t)
    },
    onKeyDown: (e) => {
      if (e.key === 'Enter' && e.target === e.currentTarget) open(t)
    },
  }
}
