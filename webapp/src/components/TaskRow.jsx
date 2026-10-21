import { memo, useState } from 'react'
import { KIND, PRIORITY, fmtRel, fmtSpent } from '../format.js'
import Avatar from './Avatar.jsx'
import { PhotoBlock } from './Media.jsx'
import { kindTag } from '../media.js'
import VoicePlayer from './VoicePlayer.jsx'
import ActionButtons from './ActionButtons.jsx'
import { useTaskView } from './actions.jsx'

const LONG = 140

// Строка списка задач для ноутбука и ПК: колонки «Прораб · Задача · Статус и действия» выровнены по всем строкам.
export default memo(function TaskRow({ t: raw, tz }) {
  const t = useTaskView(raw)
  const [open, setOpen] = useState(false)
  const pr = PRIORITY[t.priority]
  const k = KIND[t.kind]
  const long = t.text.length > LONG

  return (
    <article className="trow" style={{ '--pc': pr.color }}>
      <div className="trow__who">
        <Avatar id={t.foreman_id} name={t.foreman} size={38} />
        <div>
          <b>{t.foreman}</b>
          <span className="muted">#{t.id} · {fmtRel(t.created_at, tz)}</span>
        </div>
      </div>

      <div className="trow__body">
        {t.media?.url && t.kind !== 'voice' && <PhotoBlock media={t.media} alt={t.text || 'Фото задачи'} compact />}
        <div className="trow__main">
          {t.text ? (
            <p className={`trow__text ${open ? 'open' : ''} ${long ? 'long' : ''}`} onClick={() => long && setOpen(!open)} title={long ? 'Развернуть' : undefined}>
              {t.text}
            </p>
          ) : (
            !t.media && <p className="trow__text muted">{k.icon} {k.label}{t.kind === 'video' || t.kind === 'document' ? ' — откройте в боте' : ''}</p>
          )}
          {t.kind === 'voice' && t.media?.url && <VoicePlayer media={t.media} id={t.id} compact />}
          <div className="trow__tags">
            <span className="tag"><i className="dot" style={{ background: pr.color }} />{pr.one}</span>
            <span className="tag">{kindTag(t)}</span>
            {t.status === 'done' && t.closed_at && <span className="tag tag--ok">за {fmtSpent(t.created_at, t.closed_at)}</span>}
          </div>
        </div>
      </div>

      <div className="trow__act">
        <ActionButtons t={t} size="sm" />
      </div>
    </article>
  )
})
