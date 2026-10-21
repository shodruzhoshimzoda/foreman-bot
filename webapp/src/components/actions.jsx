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
