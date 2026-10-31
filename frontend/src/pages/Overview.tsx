import { FilePdfOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, App, Button, Skeleton, Tag } from 'antd'
import dayjs from 'dayjs'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, download } from '../api'
import Chart from '../components/Chart'
import FilterBar from '../components/FilterBar'
import { Empty, ExportMenu, fmtHours, PageHead, Panel, PlatformTag } from '../components/ui'
import { toSearch, useFilters, type FilterState } from '../filters'
import { C, PLATFORM_COLOR, PRIO_COLOR, PRIO_LABEL, SENT_COLOR, SENT_LABEL } from '../theme'
import type { Cluster } from '../types'

interface Overview {
  kpis: {
    total: number; prev_total: number | null; total_delta_pct: number | null; mood_index: number; mood_delta: number | null
    high_priority_share: number; review_share: number; resolved_share: number; urgent: number; direct: number
    avg_hours_to_transfer: number | null; avg_hours_to_resolve: number | null
  }
  sentiment: Record<string, number>
  daily: { date: string; positive: number; neutral: number; negative: number }[]
  by_source: { source_id: number; name: string; count: number; is_synthetic: boolean }[]
  by_department: { code: string; name: string; count: number; positive: number; neutral: number; negative: number }[]
  by_district: { district: string; count: number; negative: number; neg_share: number }[]
  by_type: Record<string, number>
  top_problems: Cluster[]
  hot_topics: Cluster[]
  by_platform: { platform: string; name: string; count: number; positive: number; neutral: number; negative: number }[]
  multi_platform_problems: Cluster[]
  geo: Record<string, number>
}

function moodWord(v: number) {
  if (v <= -40) return 'Жители заметно недовольны'
  if (v <= -10) return 'Преобладают жалобы'
  if (v < 10) return 'Настроение смешанное'
  return 'Преобладают положительные отзывы'
}

export function ProblemRow({ c, onOpen }: { c: Cluster; onOpen: (id: number) => void }) {
  return (
    <div className="prob" onClick={() => onOpen(c.id)} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen(c.id)}>
      <span className="prob-bar" style={{ background: PRIO_COLOR[c.priority] }} />
      <div>
        <div className="prob-title">{c.title}</div>
        <div className="prob-meta">
          {c.department_name} · {c.item_count} обращ.{c.count_24h ? ` · +${c.count_24h} за сутки` : ''}
          {c.has_urgent && <Tag color="red" style={{ marginLeft: 6 }}>срочно</Tag>}
          {c.is_hot && <Tag color="volcano" style={{ marginLeft: 4 }}>растёт</Tag>}
        </div>
        {c.multi_platform && <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
          {c.platforms.filter((p) => !['demo', 'upload'].includes(p)).map((p) => <PlatformTag key={p} value={p} />)}</div>}
      </div>
      <div className="prob-score"><span className="figure">{Math.round(c.priority_score)}</span>{PRIO_LABEL[c.priority].toLowerCase()}</div>
    </div>
  )
}

export default function Overview() {
  const { filters } = useFilters()
  const nav = useNavigate()
  const [, setSp] = useSearchParams()
  const { message } = App.useApp()
  const { data, isLoading, error } = useQuery({
    queryKey: ['overview', filters], queryFn: () => api.get<Overview>('/api/stats/overview', filters),
  })
  const drill = (extra: FilterState) => nav(`/feed?${toSearch({ ...filters, ...extra })}`)
  const openProblem = (id: number) => setSp((p) => { const n = new URLSearchParams(p); n.set('problem', String(id)); return n })
  const report = async () => {
    message.loading({ content: 'Формируем сводку…', key: 'r' })
    try { await download('/api/export/report.pdf', filters); message.success({ content: 'Сводка скачана', key: 'r' }) }
    catch (e) { message.error({ content: (e as Error).message, key: 'r' }) }
  }

  const k = data?.kpis
  const synthetic = data?.by_source.some((s) => s.is_synthetic)
  return (
    <>
      <PageHead title="Общая картина" sub={<>Обращения жителей <b>города Павлодар</b> из всех платформ: тональность и главные проблемы за период</>}
        extra={<>
          <Button icon={<FilePdfOutlined />} onClick={report}>Сводка PDF</Button>
          <ExportMenu base="/api/export/items" params={filters} label="Обращения" />
        </>} />
      <FilterBar />
      {error && <Alert type="error" showIcon title={(error as Error).message} />}
      {isLoading && <Skeleton active paragraph={{ rows: 12 }} />}
      {data && k && k.total === 0 && (
        <Panel><Empty title="За выбранный период обращений нет"
          action={<Button onClick={() => nav('/sources')}>Перейти к источникам и сбору</Button>}>
          Расширьте период или запустите сбор данных из источников.</Empty></Panel>
      )}
      {data && k && k.total > 0 && (
        <>
          {synthetic && (
            <Alert type="info" showIcon style={{ marginBottom: 14 }} title="В выборке есть демо-набор (синтетические сообщения)"
              description="Чтобы видеть только данные из реальных источников, выберите «Только реальные» в фильтре «Данные»." />
          )}
          {data.geo && (data.geo.possible || data.geo.not_local) ? (
            <div className="muted" style={{ fontSize: 13.5, marginBottom: 10 }}>
              В аналитике только сообщения о Павлодаре: {data.geo.local ?? 0}.{' '}
              {data.geo.possible ? <a onClick={() => nav('/geo')}>Ждут проверки геопривязки: {data.geo.possible}.</a> : null}{' '}
              {data.geo.not_local ? <a onClick={() => nav('/feed?days=' + (filters.days ?? '30'))}>Исключено как не относящиеся к городу: {data.geo.not_local}.</a> : null}
            </div>
          ) : null}
          <section className="pulse" aria-label="Индекс настроения">
            <div className="pulse-row">
              <div>
                <div className="figure pulse-index">{k.mood_index > 0 ? '+' : ''}{Math.round(k.mood_index)}</div>
                <div className="pulse-delta" style={{ color: k.mood_delta === null ? 'rgba(255,255,255,.6)' : k.mood_delta >= 0 ? '#7FD8A6' : '#F0A08F' }}>
                  {k.mood_delta === null ? 'нет данных за прошлый период' : `${k.mood_delta >= 0 ? '+' : ''}${k.mood_delta} к прошлому периоду`}
                </div>
              </div>
              <div className="pulse-label">
                <b style={{ color: '#fff', fontSize: 16 }}>Индекс настроения города.</b><br />
                {moodWord(k.mood_index)}. Доля положительных минус доля отрицательных, в процентных пунктах.
              </div>
              <div className="pulse-stats">
                <div className="pulse-stat"><span className="figure">{k.total}</span><span>обращений{k.total_delta_pct !== null && ` (${k.total_delta_pct >= 0 ? '+' : ''}${k.total_delta_pct}%)`}</span></div>
                <div className="pulse-stat"><span className="figure">{data.sentiment.negative}</span><span>отрицательных</span></div>
                <div className="pulse-stat"><span className="figure">{k.urgent}</span><span>с маркерами срочности</span></div>
              </div>
            </div>
            <div className="pulse-strip">
              <Chart height={110} onClick={(p) => {
                const d = data.daily[p.dataIndex]?.date
                if (d) drill({ days: undefined, date_from: dayjs(d).startOf('day').toISOString(), date_to: dayjs(d).endOf('day').toISOString(), sentiment: p.seriesName ? Object.keys(SENT_LABEL).find((s) => SENT_LABEL[s] === p.seriesName) : undefined })
              }} option={{
                grid: { left: 0, right: 0, top: 4, bottom: 0, containLabel: false },
                xAxis: { type: 'category', data: data.daily.map((d) => d.date), show: false },
                yAxis: { type: 'value', show: false },
                tooltip: { trigger: 'axis', formatter: (ps: unknown) => {
                  const arr = ps as { axisValue: string; seriesName: string; value: number }[]
                  return `${dayjs(arr[0].axisValue).format('D MMMM')}<br/>` + arr.map((x) => `${x.seriesName}: ${x.value}`).join('<br/>')
                } },
                series: (['negative', 'neutral', 'positive'] as const).map((s) => ({
                  name: SENT_LABEL[s], type: 'bar', stack: 'd', barCategoryGap: '18%',
                  data: data.daily.map((d) => d[s]),
                  itemStyle: { color: s === 'negative' ? '#E07A62' : s === 'neutral' ? '#6F849B' : '#5BC08A' },
                })),
              }} />
              <div className="pulse-legend">
                <span><i style={{ background: '#E07A62' }} />отрицательные</span>
                <span><i style={{ background: '#6F849B' }} />нейтральные</span>
                <span><i style={{ background: '#5BC08A' }} />положительные</span>
                <span style={{ marginLeft: 'auto' }}>по дням · нажмите на день, чтобы открыть обращения</span>
              </div>
            </div>
          </section>

          <div className="kpis">
            <Kpi label="Высокий приоритет" value={`${k.high_priority_share}%`} note="обращений в проблемах высокого приоритета" onClick={() => drill({ priority: 'high' })} />
            <Kpi label="Требуют проверки" value={`${k.review_share}%`} note="уверенность ИИ ниже порога" onClick={() => nav('/review')} />
            <Kpi label="Решено" value={`${k.resolved_share}%`} note="статус «решено» или «закрыто»" onClick={() => drill({ status: 'resolved,closed' })} />
            <Kpi label="До передачи" value={fmtHours(k.avg_hours_to_transfer)} note="среднее время от обращения до передачи" />
            <Kpi label="До решения" value={fmtHours(k.avg_hours_to_resolve)} note="среднее время от обращения до решения" />
          </div>

          <div className="grid g-hero">
            <Panel title="Топ-5 проблем" note="по расчётному приоритету; нажмите, чтобы открыть" extra={<Button type="link" onClick={() => nav('/problems')}>Все проблемы</Button>}>
              {data.top_problems.length ? data.top_problems.map((c) => <ProblemRow key={c.id} c={c} onOpen={openProblem} />)
                : <Empty title="Проблем пока нет">Похожие обращения объединятся в проблемы после анализа.</Empty>}
            </Panel>
            <Panel title="Тональность" note="нажмите на сектор, чтобы открыть обращения">
              <Chart height={250} onClick={(p) => drill({ sentiment: Object.keys(SENT_LABEL).find((s) => SENT_LABEL[s] === p.name) })} option={{
                tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
                legend: { bottom: 0, icon: 'circle', itemWidth: 9 },
                series: [{
                  type: 'pie', radius: ['52%', '76%'], center: ['50%', '45%'], avoidLabelOverlap: true,
                  label: { formatter: '{d}%', fontSize: 13 }, itemStyle: { borderColor: '#fff', borderWidth: 2 },
                  data: (['negative', 'neutral', 'positive'] as const).map((s) => ({ name: SENT_LABEL[s], value: data.sentiment[s], itemStyle: { color: SENT_COLOR[s] } })),
                }],
              }} />
            </Panel>
          </div>

          {data.hot_topics.length > 0 && (
            <Panel title="Горячие темы за 24 часа" note="рост обращений в 1,5 раза и больше к предыдущим суткам" style={{ marginTop: 16 }}>
              {data.hot_topics.map((c) => <ProblemRow key={c.id} c={c} onOpen={openProblem} />)}
            </Panel>
          )}

          <div className="grid g-2" style={{ marginTop: 16 }}>
            <Panel title="Платформы" note="объём и тональность по платформам; нажмите, чтобы открыть обращения">
              <Chart height={Math.max(200, data.by_platform.length * 38 + 40)} onClick={(p) => drill({ platform: data.by_platform[p.dataIndex]?.platform })} option={{
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                legend: { top: 0, right: 0, icon: 'circle', itemWidth: 9 },
                grid: { left: 4, right: 16, top: 28, bottom: 4, containLabel: true },
                xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                yAxis: { type: 'category', inverse: true, data: data.by_platform.map((d) => d.name), axisTick: { show: false },
                  axisLabel: { color: (_: unknown, i?: number) => PLATFORM_COLOR[data.by_platform[i ?? 0]?.platform] ?? C.text, fontWeight: 'bold' } as object },
                series: (['negative', 'neutral', 'positive'] as const).map((s) => ({
                  name: SENT_LABEL[s], type: 'bar', stack: 'p', barMaxWidth: 20, data: data.by_platform.map((d) => d[s]), itemStyle: { color: SENT_COLOR[s] },
                })),
              }} />
            </Panel>
            <Panel title="Проблемы на нескольких платформах" note="одна и та же проблема обсуждается в разных соцсетях — сильный сигнал">
              {data.multi_platform_problems.length ? data.multi_platform_problems.map((c) => <ProblemRow key={c.id} c={c} onOpen={openProblem} />)
                : <Empty title="Пока нет">Проблема появится здесь, когда о ней напишут минимум на двух платформах.</Empty>}
            </Panel>
            <Panel title="Обращения по подразделениям" note="нажмите на столбец, чтобы открыть обращения">
              <Chart height={Math.max(220, data.by_department.length * 30)} onClick={(p) => drill({ department: data.by_department[p.dataIndex]?.code })} option={{
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                legend: { top: 0, right: 0, icon: 'circle', itemWidth: 9 },
                grid: { left: 4, right: 16, top: 28, bottom: 4, containLabel: true },
                xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                yAxis: { type: 'category', inverse: true, data: data.by_department.map((d) => d.name), axisTick: { show: false } },
                series: (['negative', 'neutral', 'positive'] as const).map((s) => ({
                  name: SENT_LABEL[s], type: 'bar', stack: 'x', barMaxWidth: 18, data: data.by_department.map((d) => d[s]), itemStyle: { color: SENT_COLOR[s] },
                })),
              }} />
            </Panel>
            <Panel title="Районы Павлодара" note="где указано место: число обращений и доля негатива">
              {data.by_district.length ? (
                <Chart height={Math.max(220, data.by_district.length * 30)} onClick={(p) => drill({ district: data.by_district[p.dataIndex]?.district })} option={{
                  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: unknown) => {
                    const i = (ps as { dataIndex: number }[])[0].dataIndex; const d = data.by_district[i]
                    return `${d.district}<br/>Обращений: ${d.count}<br/>Негатив: ${Math.round(d.neg_share * 100)}%`
                  } },
                  grid: { left: 4, right: 40, top: 8, bottom: 4, containLabel: true },
                  xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                  yAxis: { type: 'category', inverse: true, data: data.by_district.map((d) => d.district), axisTick: { show: false } },
                  series: [{ type: 'bar', barMaxWidth: 18, label: { show: true, position: 'right', formatter: (p: { dataIndex: number }) => `${Math.round(data.by_district[p.dataIndex].neg_share * 100)}%`, color: C.muted, fontSize: 12 },
                    data: data.by_district.map((d) => ({ value: d.count, itemStyle: { color: d.neg_share >= 0.7 ? C.brick : d.neg_share >= 0.4 ? C.gold : C.sky } })) }],
                }} />
              ) : <Empty title="Районы не указаны">Район извлекается из текста, когда житель его называет.</Empty>}
            </Panel>
            <Panel title="Источники" note="откуда приходят обращения">
              <Chart height={Math.max(180, data.by_source.length * 34)} onClick={(p) => drill({ source: String(data.by_source[p.dataIndex]?.source_id) })} option={{
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: 4, right: 30, top: 8, bottom: 4, containLabel: true },
                xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                yAxis: { type: 'category', inverse: true, data: data.by_source.map((s) => s.name), axisTick: { show: false }, axisLabel: { width: 220, overflow: 'truncate' } },
                series: [{ type: 'bar', barMaxWidth: 18, label: { show: true, position: 'right', color: C.muted }, data: data.by_source.map((s) => ({ value: s.count, itemStyle: { color: s.is_synthetic ? C.slate : C.ink } })) }],
              }} />
            </Panel>
            <Panel title="Типы обращений">
              <Chart height={200} onClick={(p) => drill({ type: ['complaint', 'question', 'proposal', 'gratitude', 'info'][p.dataIndex] })} option={{
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: 4, right: 30, top: 8, bottom: 4, containLabel: true },
                xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                yAxis: { type: 'category', inverse: true, axisTick: { show: false }, data: ['Жалобы', 'Вопросы', 'Предложения', 'Благодарности', 'Информация'] },
                series: [{ type: 'bar', barMaxWidth: 18, itemStyle: { color: C.sky }, label: { show: true, position: 'right', color: C.muted },
                  data: ['complaint', 'question', 'proposal', 'gratitude', 'info'].map((t) => data.by_type[t] ?? 0) }],
              }} />
            </Panel>
          </div>
        </>
      )}
    </>
  )
}

function Kpi({ label, value, note, onClick }: { label: string; value: string; note: string; onClick?: () => void }) {
  return (
    <div className={`kpi ${onClick ? 'clickable' : ''}`} onClick={onClick} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => onClick && e.key === 'Enter' && onClick()}>
      <span className="kpi-label">{label}</span>
      <span className="figure kpi-value">{value}</span>
      <span className="kpi-note">{note}</span>
    </div>
  )
}
