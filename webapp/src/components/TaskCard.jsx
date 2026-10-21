import { memo, useState } from 'react'
import { KIND, PRIORITY, STATUS, fmtRel, fmtSpent } from '../format.js'
import Avatar from './Avatar.jsx'
import { PhotoBlock } from './Media.jsx'
import { kindTag } from '../media.js'
import VoicePlayer from './VoicePlayer.jsx'
import ActionButtons from './ActionButtons.jsx'
import { useTaskView } from './actions.jsx'

const LONG = 220

export default memo(function TaskCard({ t: raw, tz, hint }) {
  const t = useTaskView(raw)
  const [open, setOpen] = useState(false)
  const st = STATUS[t.status]
  const pr = PRIORITY[t.priority]
  const long = t.text.length > LONG
  const body = long && !open ? t.text.slice(0, LONG).trimEnd() + '…' : t.text

  return (
    <article className="tcard" style={{ '--pc': pr.color }}>
      <header className="tcard__head">
        <Avatar id={t.foreman_id} name={t.foreman} size={38} />
        <div className="tcard__who">
          <b>{t.foreman}</b>
          <span className="muted">#{t.id} · {fmtRel(t.created_at, tz)}</span>
        </div>
        {hint ? (
          <span className="badge badge--hint">{hint}</span>
        ) : (
          <span className="badge" style={{ '--bc': st.color }}>{st.icon} {st.label}</span>
        )}
      </header>

      {t.text && (
        <p className="tcard__text">
          {body}
          {long && <button className="link" onClick={() => setOpen(!open)}>{open ? ' свернуть' : ' ещё'}</button>}
        </p>
      )}

      {t.media?.url && t.kind !== 'voice' && <PhotoBlock media={t.media} alt={t.text || 'Фото задачи'} />}
      {t.media?.url && t.kind === 'voice' && <VoicePlayer media={t.media} id={t.id} />}
      {!t.text && !t.media && <p className="tcard__text muted">{KIND[t.kind].icon} {KIND[t.kind].label}{t.kind === 'video' || t.kind === 'document' ? ' — откройте в боте' : ''}</p>}

      <footer className="tcard__foot">
        <span className="tag"><i className="dot" style={{ background: pr.color }} />{pr.one}</span>
        <span className="tag">{kindTag(t)}</span>
        {t.status === 'done' && t.closed_at && <span className="tag tag--ok">за {fmtSpent(t.created_at, t.closed_at)}</span>}
      </footer>

      <ActionButtons t={t} size="lg" showStatus={false} />
    </article>
  )
})
