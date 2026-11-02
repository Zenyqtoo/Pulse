import { ArrowRightOutlined, EnvironmentOutlined, LockOutlined, SafetyCertificateOutlined, SearchOutlined, FieldTimeOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Input, Segmented, Select, Skeleton } from 'antd'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../context'
import type { Cluster, Paged } from '../types'

// The desk keeps its own selection in the URL, so going to the source messages and back restores it.
const VIEWS = ['Все', 'Высокий приоритет', 'Растут', 'Ждут реакции', 'В работе'] as const
type View = (typeof VIEWS)[number]
const MATCH: Record<View, (c: Cluster) => boolean> = {
  'Все': () => true,
  'Высокий приоритет': (c) => c.priority === 'high',
  'Растут': (c) => c.is_hot,
  'Ждут реакции': (c) => c.status === 'new',
  'В работе': (c) => c.status !== 'new',
}
const DESK_SIZE = 5
const num = (id: number) => `№${id}`

// Why a problem is on the desk — only facts the system actually holds about it.
function reasons(c: Cluster): string[] {
  const out: string[] = []
  if (c.has_urgent) out.push('В текстах есть признаки срочности — нужна проверка сотрудником.')
  if (c.count_24h > 0) out.push(`За последние 24 часа — ${c.count_24h}, за предыдущие сутки — ${c.count_prev_24h}.`)
  if (c.multi_platform) out.push(`Обсуждается на нескольких платформах (${c.source_count} источн.).`)
  if (c.priority === 'high' && !c.priority_factors?.forced_by_life_threat) out.push('Высокий балл приоритета: негатив, объём и охват сообщений.')
  if (c.priority_factors?.forced_by_life_threat) out.push('Приоритет поднят правилом «угроза жизни».')
  if (!out.length) out.push(`${c.item_count} похожих обращений объединены в одну проблему.`)
  return out.slice(0, 3)
}

function badge(c: Cluster) {
  if (c.synthetic) return <span className="case-badge origin">Учебные данные</span>
  if (c.priority === 'high') return <span className="case-badge high">Высокий приоритет</span>
  if (c.is_hot) return <span className="case-badge medium">Растёт</span>
  return <span className="case-badge">На контроле</span>
}

export default function Home() {
  const { meta, user, can } = useApp()
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const view = (VIEWS as readonly string[]).includes(sp.get('view') ?? '') ? sp.get('view') as View : 'Все'
  const search = sp.get('q') ?? ''
  const department = sp.get('department') ?? undefined
  const origin = sp.get('origin') ?? undefined
  const patch = (k: string, v?: string) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n }, { replace: true })

  const { data, isLoading, error } = useQuery({
    queryKey: ['clusters', 'desk', department, origin],
    queryFn: () => api.get<Paged<Cluster>>('/api/clusters', { page_size: 200, department, origin, status: 'new,transferred,in_progress' }),
    refetchInterval: 60_000,
  })
  const { data: ops } = useQuery({
    queryKey: ['ops'], queryFn: () => api.get<{ review_queue: number; geo_queue: number; new_direct: number; overdue: number }>('/api/stats/operations'),
    refetchInterval: 30_000, enabled: can('operator'),
  })

  const all = data?.items ?? []
  const q = search.trim().toLowerCase()
  const visible = all.filter((c) => MATCH[view](c) && (!q || `${c.title} ${c.district ?? ''} ${c.department_name}`.toLowerCase().includes(q)))
  const [lead, ...rest] = visible
  const open = (id: number) => setSp((p) => { const n = new URLSearchParams(p); n.set('decision', String(id)); return n })
  const counters: [View, string, string, number][] = [
    ['Высокий приоритет', 'Высокий приоритет', 'Проверить в первую очередь', all.filter(MATCH['Высокий приоритет']).length],
    ['Растут', 'Растут за сутки', 'Сообщений больше, чем днём ранее', all.filter(MATCH['Растут']).length],
    ['Ждут реакции', 'Ждут реакции', 'Ещё не переданы ответственным', all.filter(MATCH['Ждут реакции']).length],
  ]
  const today = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'Asia/Almaty' }).format(new Date())
  const resetAll = () => setSp(new URLSearchParams(), { replace: true })

  return (
    <div className="desk">
      <div className="desk-heading">
        <div>
          <div className="eyebrow">{(meta?.city_name ?? 'Павлодар').toUpperCase()} · {today.toUpperCase()}</div>
          <h1>Требует внимания</h1>
          <p>{DESK_SIZE} самых важных проблем по приоритету. Откройте карточку, чтобы проверить факты перед решением.</p>
        </div>
        <button className="text-action" onClick={() => nav('/analytics')}>Графики и аналитика <ArrowRightOutlined /></button>
      </div>

      <div className="desk-counters" role="group" aria-label="Быстрые подборки">
        {counters.map(([target, label, note, n], i) => (
          <button key={target} className={`desk-counter counter-${i}${view === target ? ' active' : ''}`} aria-pressed={view === target}
            onClick={() => patch('view', view === target ? undefined : target)}>
            <span>{label}</span><strong>{isLoading ? '—' : n}</strong><small>{note}</small>
          </button>
        ))}
      </div>

      <div className="desk-toolbar">
        <Segmented aria-label="Показать проблемы" value={view} onChange={(v) => patch('view', v === 'Все' ? undefined : String(v))} options={[...VIEWS]} />
        <div className="desk-search">
          <Select aria-label="Происхождение данных" value={origin ?? 'all'} popupMatchSelectWidth={false} className="origin-select"
            onChange={(v) => patch('origin', v === 'all' ? undefined : v)}
            options={[{ value: 'all', label: 'Все данные' }, { value: 'real', label: 'Только реальные' }, { value: 'synthetic', label: 'Только учебные' }]} />
          <Input allowClear prefix={<SearchOutlined />} placeholder="Найти проблему или район" aria-label="Поиск по проблемам"
            value={search} onChange={(e) => patch('q', e.target.value)} />
          {!user?.department_code && (
            <Select allowClear placeholder="Все подразделения" aria-label="Подразделение" value={department} popupMatchSelectWidth={false}
              onChange={(v) => patch('department', v)} options={meta?.departments.map((d) => ({ value: d.code, label: d.name }))} />
          )}
        </div>
      </div>

      {error && <Alert type="error" showIcon title="Не удалось загрузить проблемы" description={(error as Error).message} />}
      {isLoading && <Skeleton active paragraph={{ rows: 8 }} />}
      {!isLoading && !error && !lead && (
        <div className="desk-empty">
          <h2>{all.length ? 'По этому выбору проблем нет' : 'Активных проблем нет'}</h2>
          <p>{all.length ? 'Измените подборку или текст поиска.' : 'Новые обращения появятся здесь после сбора и анализа.'}</p>
          {all.length > 0 && <Button onClick={resetAll}>Показать все</Button>}
        </div>
      )}

      {lead && (
        <div className="desk-feature-grid">
          <article className="lead-case">
            <div className="case-top"><span className="eyebrow">ПЕРВЫМ ДЕЛОМ · ПРОБЛЕМА {num(lead.id)}</span>{badge(lead)}</div>
            <h2>{lead.title}</h2>
            <p className="case-location">{lead.district || 'Район не определён'}<span>·</span>{lead.department_name}</p>
            <div className="case-reason">
              <span className="signal-dot" />
              <div><b>Почему в списке</b><ul>{reasons(lead).map((r) => <li key={r}>{r}</li>)}</ul></div>
            </div>
            <div className="case-numbers">
              <div><strong>{lead.item_count}</strong><span>сообщений в проблеме</span></div>
              <div><strong>{lead.count_24h}</strong><span>за последние 24 часа</span></div>
              <div><strong>{lead.source_count}</strong><span>{lead.source_count === 1 ? 'источник' : 'источников'}</span></div>
            </div>
            <div className="case-actions">
              <Button type="primary" size="large" onClick={() => open(lead.id)}>Подготовить данные для решения <ArrowRightOutlined /></Button>
              <Link className="text-action" to={`/feed?cluster_id=${lead.id}&days=365`}>Исходные обращения</Link>
            </div>
          </article>

          {can('operator') ? (
            <aside className="decision-intro queue-panel" aria-label="Мои очереди">
              <span className="eyebrow">МОИ ОЧЕРЕДИ</span>
              <h2>Что ждёт<br />вашей <em>проверки</em></h2>
              {([
                ['/review', <SafetyCertificateOutlined key="r" />, 'Проверить выводы ИИ', 'ИИ не уверен в подразделении или тональности', ops?.review_queue],
                ['/geo', <EnvironmentOutlined key="g" />, 'Уточнить место', 'Неясно, относится ли сообщение к Павлодару', ops?.geo_queue],
                ['/direct', <LockOutlined key="d" />, 'Личные обращения', 'Новые сообщения в аккаунты акимата', ops?.new_direct],
                ['/feed?status=new&days=365&voice=resident', <FieldTimeOutlined key="o" />, 'Без реакции дольше 48 ч', 'Сообщения жителей в статусе «Новое»', ops?.overdue],
              ] as const).map(([to, icon, label, note, n]) => (
                <Link key={to} to={to} className="queue-row">
                  <span className="queue-icon">{icon}</span>
                  <span><b>{label}</b><small>{note}</small></span>
                  <strong>{n ?? '—'}</strong>
                </Link>
              ))}
              <div className="intro-note">Система готовит информацию. Решение остаётся за человеком.</div>
            </aside>
          ) : (
            <aside className="decision-intro" aria-label="Как читать экран">
              <span className="eyebrow">КАК ЧИТАТЬ ЭКРАН</span>
              <h2>От сообщения<br />к обоснованному<br /><em>решению.</em></h2>
              <ol>
                <li><span>01</span><div><b>Заметить проблему</b><p>Похожие обращения объединены в одну проблему.</p></div></li>
                <li><span>02</span><div><b>Проверить доказательства</b><p>Каждое число можно сверить с исходными сообщениями.</p></div></li>
                <li><span>03</span><div><b>Принять решение</b><p>Его принимает сотрудник с учётом фактов и ресурсов.</p></div></li>
              </ol>
              <div className="intro-note">Личные обращения скрыты для роли «Наблюдатель».</div>
            </aside>
          )}
        </div>
      )}

      {rest.length > 0 && (
        <>
          <div className="desk-section-heading"><h2>Также требуют внимания</h2><span>Показано {Math.min(visible.length, DESK_SIZE)} из {visible.length}</span></div>
          <div className="case-grid">
            {rest.slice(0, DESK_SIZE - 1).map((c) => (
              <article className="small-case" key={c.id}>
                <div className="case-top"><span className="case-id">ПРОБЛЕМА {num(c.id)} · {c.department_name}</span>{badge(c)}</div>
                <h3>{c.title}</h3>
                <p>{c.district || 'Район не определён'} · {reasons(c)[0]}</p>
                <div className="small-case-metrics"><b>{c.item_count} сообщений</b><span>{c.count_24h} за 24 часа</span></div>
                <button className="case-open" onClick={() => open(c.id)}>Подготовить данные для решения <ArrowRightOutlined /></button>
              </article>
            ))}
          </div>
        </>
      )}

      {lead && (
        <div className="desk-bottom">
          <p>Подборки и поиск работают по активным проблемам: новые, переданные и в работе.{data && data.total > all.length ? ` Загружены первые ${all.length} из ${data.total}.` : ''}</p>
          <Button onClick={() => nav('/problems')}>Все проблемы <ArrowRightOutlined /></Button>
        </div>
      )}
      <div className="desk-data-note"><span className="signal-dot" />{meta?.sources.some((s) => s.is_synthetic)
        ? 'Реальные и учебные (синтетические) данные никогда не объединяются в одну проблему. Учебные отмечены, их можно скрыть переключателем «Только реальные».'
        : 'Сводки строятся по собранным сообщениям. Проверяйте первоисточники перед решением.'}</div>
    </div>
  )
}
