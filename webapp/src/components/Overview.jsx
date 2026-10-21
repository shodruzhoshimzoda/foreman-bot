import { memo } from 'react'
import { fmtAge } from '../format.js'
import Hero from './Hero.jsx'
import DailyChart from './DailyChart.jsx'
import Breakdown from './Breakdown.jsx'
import TaskCard from './TaskCard.jsx'
import TaskList from './TaskList.jsx'
import { useTaskActions } from './actions.jsx'

export default memo(function Overview({ data, onOpenTasks }) {
  const { summary: s, tz } = data
  const { overrides } = useTaskActions()
  // закрытые в этом сеансе задачи сразу пропадают из «дольше всего в работе»
  const stale = data.stale.filter((t) => !overrides[t.id] || overrides[t.id].status === 'new')
  return (
    <>
      <Hero s={s} days={data.days} onOpenTasks={onOpenTasks} />
      {s.total === 0 && <p className="empty">За выбранный период задач не было.</p>}

      <div className={`ov-grid ${stale.length ? '' : 'ov-grid--solo'}`}>
        <div className="ov-main">
          <DailyChart daily={data.daily} chartDays={data.daily_days} allTime={data.days === 0} />
          <Breakdown byKind={data.by_kind} byPriority={data.by_priority} total={s.total} />
        </div>
        {stale.length > 0 && (
          <section className="ov-side">
            <h2>⏳ Дольше всего в работе</h2>
            <div className="cards">
              {stale.map((t) => <TaskCard key={t.id} t={t} tz={tz} hint={`ждёт ${fmtAge(t.created_at)}`} />)}
            </div>
          </section>
        )}
      </div>

      {data.recent.length > 0 && (
        <section>
          <h2>Последние задачи</h2>
          <TaskList tz={tz} tasks={data.recent} />
          <button className="btn btn--soft" onClick={() => onOpenTasks({})}>Все задачи →</button>
        </section>
      )}
    </>
  )
})
