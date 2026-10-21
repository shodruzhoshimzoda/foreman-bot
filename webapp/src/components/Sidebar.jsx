// На телефоне это нижняя панель вкладок, на ноутбуке и ПК — боковая панель (раскладка задаётся в CSS).
const ICONS = {
  overview: <path d="M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z" />,
  team: <path d="M16 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm0 2c-2.7 0-6 1.3-6 4v2h8v-2c0-1.5.6-2.7 1.5-3.6A9 9 0 0 0 8 13Zm8 0c-2.7 0-6 1.3-6 4v2h12v-2c0-2.7-3.3-4-6-4Z" />,
  tasks: <path d="M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm2 4v2h10V8H7Zm0 4v2h10v-2H7Zm0 4v2h6v-2H7Z" />,
}

export const TABS = [['overview', 'Обзор'], ['team', 'Прорабы'], ['tasks', 'Задачи']]

export default function Sidebar({ tab, onChange, badge, fullscreen }) {
  return (
    <aside className="side">
      <div className="side__brand">
        <span className="side__logo">📊</span>
        <div>
          <b>Дашборд</b>
          <small>задачи прорабов</small>
        </div>
      </div>

      <nav className="side__nav" aria-label="Разделы">
        {TABS.map(([key, label], i) => (
          <button key={key} className={tab === key ? 'on' : ''} onClick={() => onChange(key)} aria-current={tab === key ? 'page' : undefined}>
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{ICONS[key]}</svg>
            <span className="side__label">{label}</span>
            {key === 'tasks' && badge > 0 && <i className="side__badge">{badge > 99 ? '99+' : badge}</i>}
            <kbd>{i + 1}</kbd>
          </button>
        ))}
      </nav>

      <div className="side__foot">
        {fullscreen.can && (
          <button className="side__btn" onClick={fullscreen.toggle}>
            {fullscreen.on ? '⤡ Свернуть окно' : '⤢ На весь экран'}
          </button>
        )}
        <div className="side__keys">
          <div><kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> разделы</div>
          <div><kbd>R</kbd> обновить</div>
        </div>
      </div>
    </aside>
  )
}
