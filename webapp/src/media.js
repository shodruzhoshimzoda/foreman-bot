import { mediaSrc } from './api.js'
import { KIND } from './format.js'

// Номера фото в задаче. У альбома бывают и видео — в дашборде их не показываем (открываются в боте).
export function photoIndexes(media) {
  if (!media?.items) return [0]
  return media.items.flatMap((it, i) => (it.kind === 'photo' ? [i] : []))
}

// Адрес вложения №index: ссылка задачи подписана сервером, номер и размер (?v=thumb) подпись не меняют.
export function itemSrc(media, index = 0, extra = {}) {
  if (media.srcs) return media.srcs[index] // тестовые данные: готовые картинки
  return mediaSrc(media.url, index ? { ...extra, i: index } : extra)
}

// Подпись вида: «📷 Фото ×3 · 🎥 Видео ×1»
export function kindTag(t) {
  const k = KIND[t.kind]
  if (!t.album) return `${k.icon} ${k.label}`
  const items = t.media?.items
  if (!items) return `${k.icon} ${k.label} ×${t.album}`
  const photos = items.filter((i) => i.kind === 'photo').length
  return [photos && `📷 Фото ×${photos}`, items.length - photos && `🎥 Видео ×${items.length - photos}`].filter(Boolean).join(' · ')
}
