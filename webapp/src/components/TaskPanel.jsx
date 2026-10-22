import { useEffect, useState } from 'react'
import { fetchTask } from '../api.js'
import { useLayer } from '../backStack.js'
import { KIND, PRIORITY, STATUS, fmtAge, fmtFull, fmtRel, fmtSpent } from '../format.js'
import { kindTag } from '../media.js'
import ActionButtons from './ActionButtons.jsx'
import Avatar from './Avatar.jsx'
import { PhotoGallery } from './Media.jsx'
import VoicePlayer from './VoicePlayer.jsx'
import { useTaskView } from './actions.jsx'

// Страница одной задачи: на ПК — панель справа (список остаётся виден), на телефоне — на весь экран.
export default function TaskPanel({ task: preview, tz, onClose, onForeman }) {
  const [full, setFull] = useState(null)
  const [failed, setFailed] = useState(false)
  const t = useTaskView(full || preview)

  useLayer(onClose) // Esc и кнопка «назад» в Telegram

  useEffect(() => {
    const ctl = new AbortController()
    setFull(null)
    setFailed(false)
    fetchTask(preview.id, ctl.signal)
      .then((r) => setFull(r.task))
      .catch((e) => e.name !== 'AbortError' && (e.status === 404 ? onClose() : setFailed(true)))
    return () => ctl.abort()
  }, [preview.id, onClose])

  useEffect(() => {
    document.body.classList.add('has-panel')
    return () => document.body.classList.remove('has-panel')
  }, [])

  const pr = PRIORITY[t.priority]
  const st = STATUS[t.status]
  const k = KIND[t.kind]
  const closed = t.status !== 'new' && t.closed_at
  const photos = t.media && t.kind !== 'voice'
  const videos = t.media?.items ? t.media.items.filter((i) => i.kind === 'video').length : t.album && !t.media ? t.album : 0
  const hasMedia = photos || t.kind === 'voice' || videos > 0 || t.kind === 'document' || t.kind === 'video'

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel" role="dialog" aria-label={`Задача #${t.id}`} onClick={(e) => e.stopPropagation()} style={{ '--pc': pr.color }}>
        <header className="panel__head">
          <button className="panel__back" onClick={onClose} aria-label="Закрыть">
            <span className="panel__back-arrow">‹</span>
            <span className="panel__back-x">✕</span>
          </button>
          <div className="panel__title">
            <b>Задача #{t.id}</b>
            <span className="muted">{fmtRel(t.created_at, tz)}</span>
          </div>
          <span className="badge" style={{ '--bc': st.color }}>{st.icon} {st.label}</span>
        </header>

        <div className="panel__body">
          <div className="panel__chips">
            <span className="tag"><i className="dot" style={{ background: pr.color }} />{pr.one}</span>
            <span className="tag">{kindTag(t)}</span>
            {t.status === 'done' && t.closed_at && <span className="tag tag--ok">за {fmtSpent(t.created_at, t.closed_at)}</span>}
          </div>

          <div className="panel__who">
            <Avatar id={t.foreman_id} name={t.foreman} size={44} />
            <div>
              <b>{t.foreman}</b>
              <span className="muted">прораб</span>
            </div>
            <button className="panel__link" onClick={() => onForeman(t.foreman_id)}>Все задачи ›</button>
          </div>

          <section>
            <h3>Описание</h3>
            {t.text ? <p className="panel__text">{t.text}</p> : <p className="muted">Без текста — только вложения.</p>}
            {failed && <p className="muted">Не удалось загрузить полный текст. Показано сокращённое описание.</p>}
          </section>

          {hasMedia && (
            <section>
              <h3>Вложения</h3>
              {photos && <PhotoGallery media={t.media} alt={t.text || 'Фото задачи'} />}
              {t.kind === 'voice' && t.media?.url && <VoicePlayer media={t.media} id={t.id} />}
              {videos > 0 && <p className="panel__note">🎥 Видео ×{videos} — откройте в боте</p>}
              {t.kind === 'document' && <p className="panel__note">📎 {k.label} — откройте в боте</p>}
              {t.kind === 'video' && !t.album && <p className="panel__note">🎥 Видео — откройте в боте</p>}
            </section>
          )}

          <section>
            <h3>Хронология</h3>
            <ol className="timeline">
              <li>
                <i className="timeline__dot" style={{ background: 'var(--accent)' }} />
                <div>
                  <b>Отправлена прорабу</b>
                  <span className="muted">{fmtFull(t.created_at, tz)}</span>
                </div>
              </li>
              {closed ? (
                <li>
                  <i className="timeline__dot" style={{ background: st.color }} />
                  <div>
                    <b>{st.icon} {st.label}</b>
                    <span className="muted">{fmtFull(t.closed_at, tz)} · через {fmtSpent(t.created_at, t.closed_at)}</span>
                  </div>
                </li>
              ) : (
                <li className="timeline__now">
                  <i className="timeline__dot timeline__dot--pulse" style={{ background: 'var(--c-active)' }} />
                  <div>
                    <b>Сейчас в работе</b>
                    <span className="muted">уже {fmtAge(t.created_at)}</span>
                  </div>
                </li>
              )}
            </ol>
          </section>
        </div>

        <footer className="panel__foot">
          <ActionButtons t={t} size="lg" />
        </footer>
      </aside>
    </div>
  )
}
