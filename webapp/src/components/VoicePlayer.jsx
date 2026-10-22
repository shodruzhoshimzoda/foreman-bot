import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { mediaSrc } from '../api.js'
import { fmtClock } from '../format.js'

const RATES = [1, 1.5, 2]
const BARS = 34
let current = null // играет одно голосовое за раз

// Telegram-WebView на iOS не умеет OGG/Opus — тогда просим у сервера M4A.
const canOgg = () => {
  try {
    return !!document.createElement('audio').canPlayType('audio/ogg; codecs=opus')
  } catch {
    return false
  }
}

// «Волна» — декоративная, но стабильная для каждой задачи
function waveform(seed) {
  let x = (Number(seed) % 2147483646) + 1
  return Array.from({ length: BARS }, (_, i) => {
    x = (x * 16807) % 2147483647
    const base = 0.35 + 0.65 * ((x - 1) / 2147483646)
    return Math.max(0.18, base * (0.75 + 0.25 * Math.sin(i / 3)))
  })
}

const Icon = ({ state }) =>
  state === 'loading' ? (
    <svg viewBox="0 0 24 24" className="spin" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="2.5" strokeDasharray="30 20" strokeLinecap="round" /></svg>
  ) : state === 'playing' ? (
    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4.2" height="14" rx="1.2" fill="currentColor" /><rect x="13.8" y="5" width="4.2" height="14" rx="1.2" fill="currentColor" /></svg>
  ) : (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.2v13.6c0 .8.9 1.3 1.6.8l10-6.8c.6-.4.6-1.2 0-1.6l-10-6.8C8.9 3.9 8 4.4 8 5.2Z" fill="currentColor" /></svg>
  )

export default memo(function VoicePlayer({ media, id, compact = false }) {
  const audio = useRef(null)
  const wantPlay = useRef(false)
  const pendingSeek = useRef(null)
  const [fmt, setFmt] = useState(() => (canOgg() ? 'ogg' : 'm4a'))
  const [st, setSt] = useState('idle') // idle | loading | playing | paused | error
  const [cur, setCur] = useState(0)
  const [dur, setDur] = useState(media.duration || 0)
  const [rate, setRate] = useState(1)
  const bars = useMemo(() => waveform(id), [id])
  const src = mediaSrc(media.url, fmt === 'm4a' ? { fmt: 'm4a' } : {})

  // после переключения на M4A продолжаем с того, что хотел пользователь
  useEffect(() => {
    const a = audio.current
    if (fmt === 'm4a' && wantPlay.current && a) {
      a.load()
      a.play().catch(() => {})
    }
  }, [fmt])

  useEffect(() => () => { if (current === audio.current) current = null }, [])

  const toggle = async () => {
    const a = audio.current
    if (st === 'error') {
      setSt('idle')
      setFmt(canOgg() ? 'ogg' : 'm4a')
      return
    }
    if (!a.paused) return a.pause()
    if (current && current !== a) current.pause()
    current = a
    wantPlay.current = true
    setSt('loading')
    try {
      await a.play()
    } catch {
      /* ошибку обработает onError */
    }
  }

  const onError = () => {
    if (fmt === 'ogg') return setFmt('m4a') // iOS и др.: пробуем M4A
    wantPlay.current = false
    setSt('error')
  }

  const seek = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const frac = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1)
    const a = audio.current
    const total = a.duration || dur
    if (!total) return
    if (a.readyState > 0) a.currentTime = frac * total
    else {
      pendingSeek.current = frac * total // метаданные ещё не загружены
      toggle()
    }
  }

  const cycleRate = () => {
    const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length]
    setRate(next)
    if (audio.current) audio.current.playbackRate = next
  }

  const progress = dur ? cur / dur : 0
  const busy = st === 'playing' || st === 'loading'

  return (
    <div className={`voice ${compact ? 'voice--compact' : ''} ${st === 'error' ? 'voice--err' : ''}`}>
      <button className="voice__btn" onClick={toggle} aria-label={st === 'playing' ? 'Пауза' : 'Воспроизвести'}>
        <Icon state={st === 'error' ? 'idle' : st} />
      </button>
      <div className="voice__main">
        {st === 'error' ? (
          <div className="voice__msg">Не удалось воспроизвести. Нажмите, чтобы повторить.</div>
        ) : (
          <div className="voice__wave" onClick={seek} role="slider" aria-label="Перемотка" aria-valuenow={Math.round(progress * 100)}>
            {bars.map((h, i) => (
              <span key={i} className={i / BARS < progress ? 'on' : ''} style={{ height: `${h * 100}%` }} />
            ))}
          </div>
        )}
        <div className="voice__meta">
          <span>{busy || cur > 0 ? `${fmtClock(cur)} / ${fmtClock(dur)}` : fmtClock(dur)}</span>
          <span>🎤 Голосовое</span>
        </div>
      </div>
      <button className="voice__rate" onClick={cycleRate} aria-label="Скорость">{rate}×</button>
      <audio
        ref={audio}
        src={src}
        preload="none"
        onPlay={(e) => { e.currentTarget.playbackRate = rate; setSt('playing') }}
        onPlaying={() => setSt('playing')}
        onWaiting={() => setSt('loading')}
        onPause={() => setSt((s) => (s === 'error' ? s : 'paused'))}
        onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          const a = e.currentTarget
          if (Number.isFinite(a.duration) && a.duration > 0) setDur(a.duration)
          if (pendingSeek.current != null) { a.currentTime = pendingSeek.current; pendingSeek.current = null }
        }}
        onEnded={(e) => { e.currentTarget.currentTime = 0; setCur(0); setSt('paused') }}
        onError={onError}
      />
    </div>
  )
})
