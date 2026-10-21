import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export const DESKTOP = '(min-width: 900px)'

// Реагирует на изменение размера окна (в Telegram Desktop окно можно растянуть или развернуть)
export function useMedia(query) {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const on = () => setMatch(mq.matches)
    mq.addEventListener('change', on)
    on()
    return () => mq.removeEventListener('change', on)
  }, [query])
  return match
}

// Ширина элемента в пикселях — график рисуется в реальных px, а не растягивается
export function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setW(Math.round(el.clientWidth))
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.target.clientWidth)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}
