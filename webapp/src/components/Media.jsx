import { createContext, memo, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useLayer } from '../backStack.js'
import { itemSrc, photoIndexes } from '../media.js'

export const LightboxContext = createContext(() => {})

// Плитка с одним фото: лениво грузится, по нажатию открывает просмотр на этом фото.
const Tile = memo(function Tile({ media, index, alt, className = '', badge = 0, more = 0 }) {
  const open = useContext(LightboxContext)
  const [state, setState] = useState('loading')
  if (state === 'error') return <div className={`ptile ptile--err ${className}`}>📷</div>
  return (
    <button className={`ptile ${state} ${className}`} onClick={() => open(media, index)} aria-label="Открыть фото">
      <img src={itemSrc(media, index, { v: 'thumb' })} alt={alt} loading="lazy" decoding="async"
        onLoad={() => setState('ok')} onError={() => setState('error')} />
      {badge > 1 && <span className="ptile__badge">🖼 {badge}</span>}
      {more > 0 && <span className="ptile__more">+{more}</span>}
    </button>
  )
})

// Фото задачи. Одно — крупно, несколько — сеткой как в Telegram (до 4 плиток, на последней «+N»).
// compact (строка таблицы на ПК) — одно превью со значком количества.
export const PhotoBlock = memo(function PhotoBlock({ media, alt, compact = false }) {
  const idx = photoIndexes(media)
  if (!idx.length) return null
  if (compact) return <Tile media={media} index={idx[0]} alt={alt} className="ptile--thumb" badge={idx.length} />
  if (idx.length === 1) return <Tile media={media} index={idx[0]} alt={alt} className="ptile--single" />
  const shown = idx.slice(0, 4)
  return (
    <div className={`pgrid pgrid--${shown.length}`}>
      {shown.map((i, k) => (
        <Tile key={i} media={media} index={i} alt={alt} more={k === shown.length - 1 ? idx.length - shown.length : 0} />
      ))}
    </div>
  )
})

// Все фото задачи крупно (панель задачи): одно — во всю ширину, несколько — по два в ряд.
export const PhotoGallery = memo(function PhotoGallery({ media, alt }) {
  const idx = photoIndexes(media)
  if (!idx.length) return null
  return (
    <div className={`pgal ${idx.length === 1 ? 'pgal--one' : ''}`}>
      {idx.map((i) => <Tile key={i} media={media} index={i} alt={alt} className="ptile--gal" />)}
    </div>
  )
})

// Просмотр на весь экран: листание (кнопки, ←/→, свайп), сначала превью, поверх подгружается оригинал.
export function Lightbox({ media, index, onClose }) {
  const list = photoIndexes(media)
  const [pos, setPos] = useState(Math.max(list.indexOf(index), 0))
  const [full, setFull] = useState(false)
  const [zoom, setZoom] = useState(false)
  const touch = useRef(null)
  const cur = list[pos]

  const go = useCallback((d) => {
    if (list.length < 2) return
    setPos((p) => (p + d + list.length) % list.length)
    setFull(false)
    setZoom(false)
  }, [list.length])

  useLayer(onClose) // Esc и «назад» в Telegram закрывают просмотр, а не то, что под ним

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === 'ArrowRight') go(1)
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [go])

  // соседние фото подгружаем заранее — листание без ожидания
  useEffect(() => {
    if (list.length < 2) return
    for (const d of [1, -1]) new Image().src = itemSrc(media, list[(pos + d + list.length) % list.length])
  }, [pos, list, media])

  const stop = (fn) => (e) => { e.stopPropagation(); fn() }
  const onTouchEnd = (e) => {
    const start = touch.current
    touch.current = null
    if (start == null || zoom) return
    const dx = e.changedTouches[0].clientX - start
    if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1)
  }

  return (
    <div className={`lb ${zoom ? 'lb--zoom' : ''}`} onClick={onClose} role="dialog" aria-label="Фото"
      onTouchStart={(e) => { touch.current = e.touches[0].clientX }} onTouchEnd={onTouchEnd}>
      <div className="lb__stage">
        <img key={`t${cur}`} className="lb__img lb__img--thumb" src={itemSrc(media, cur, { v: 'thumb' })} alt="" />
        <img key={`f${cur}`} className={`lb__img lb__img--full ${full ? 'on' : ''}`} src={itemSrc(media, cur)} alt="Фото задачи"
          onLoad={() => setFull(true)} onClick={stop(() => setZoom((z) => !z))} />
      </div>
      {!full && <div className="lb__loading">Загрузка…</div>}
      {list.length > 1 && (
        <>
          <button className="lb__nav lb__nav--prev" onClick={stop(() => go(-1))} aria-label="Предыдущее фото">‹</button>
          <button className="lb__nav lb__nav--next" onClick={stop(() => go(1))} aria-label="Следующее фото">›</button>
          <div className="lb__count">{pos + 1} / {list.length}</div>
        </>
      )}
      <button className="lb__close" onClick={stop(onClose)} aria-label="Закрыть">✕</button>
    </div>
  )
}
