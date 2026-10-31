import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Drawer, Skeleton, Table, Tooltip } from 'antd'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import Chart from '../components/Chart'
import FilterBar from '../components/FilterBar'
import { Empty, ExportMenu, fmtHours, PageHead, Panel } from '../components/ui'
import { useApp } from '../context'
import { toSearch, useFilters } from '../filters'
import { C, SENT_COLOR, SENT_LABEL } from '../theme'
import type { Cluster, Paged } from '../types'
import { ProblemRow } from './Overview'

interface Dept {
  code: string; name: string; count: number; positive: number; neutral: number; negative: number; mood_index: number
  resolved_share: number; avg_hours_to_transfer: number | null; avg_hours_to_resolve: number | null
  open_problems: number; high_problems: number; review_share: number; urgent: number; rating: number
}

export default function Departments() {
  const { filters } = useFilters()
  const nav = useNavigate()
  const [, setSp] = useSearchParams()
  const [selected, setSelected] = useState<Dept | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['departments', filters], queryFn: () => api.get<{ departments: Dept[]; rating_formula: string }>('/api/stats/departments', filters),
  })
  const rows = data?.departments ?? []
  const ranked = [...rows].sort((a, b) => b.rating - a.rating)
  return (
    <>
      <PageHead title="Подразделения" sub="Нагрузка, тональность и скорость реакции по сферам ответственности"
        extra={<ExportMenu base="/api/export/items" params={filters} label="Обращения" />} />
      <FilterBar fields={['period', 'source', 'sentiment', 'district', 'origin']} />
      {error && <Alert type="error" showIcon title={(error as Error).message} />}
      {isLoading && <Skeleton active paragraph={{ rows: 10 }} />}
      {data && !rows.length && <Panel><Empty title="Нет обращений за период">Расширьте период в фильтре.</Empty></Panel>}
      {rows.length > 0 && (
        <>
          <div className="grid g-2">
            <Panel title="Нагрузка по подразделениям" note="число обращений с разбивкой по тональности; нажмите, чтобы открыть подразделение">
              <Chart height={Math.max(260, rows.length * 32)} onClick={(p) => setSelected(rows[p.dataIndex])} option={{
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                legend: { top: 0, right: 0, icon: 'circle', itemWidth: 9 },
                grid: { left: 4, right: 16, top: 28, bottom: 4, containLabel: true },
                xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                yAxis: { type: 'category', inverse: true, data: rows.map((d) => d.name), axisTick: { show: false } },
                series: (['negative', 'neutral', 'positive'] as const).map((s) => ({
                  name: SENT_LABEL[s], type: 'bar', stack: 'x', barMaxWidth: 18, data: rows.map((d) => d[s]), itemStyle: { color: SENT_COLOR[s] },
                })),
              }} />
            </Panel>
            <Panel title="Рейтинг подразделений" note={data?.rating_formula}>
              <Chart height={Math.max(260, ranked.length * 32)} onClick={(p) => setSelected(ranked[p.dataIndex])} option={{
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: 4, right: 36, top: 8, bottom: 4, containLabel: true },
                xAxis: { type: 'value', max: 100, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                yAxis: { type: 'category', inverse: true, data: ranked.map((d) => d.name), axisTick: { show: false } },
                series: [{ type: 'bar', barMaxWidth: 16, label: { show: true, position: 'right', color: C.muted },
                  data: ranked.map((d) => ({ value: d.rating, itemStyle: { color: d.rating >= 60 ? C.green : d.rating >= 35 ? C.gold : C.brick } })) }],
              }} />
            </Panel>
          </div>
          <div className="panel" style={{ padding: 0, marginTop: 16 }}>
            <Table<Dept> rowKey="code" dataSource={rows} pagination={false} size="middle" scroll={{ x: 1000 }}
              onRow={(r) => ({ onClick: () => setSelected(r), style: { cursor: 'pointer' } })}
              columns={[
                { title: 'Подразделение', dataIndex: 'name', render: (v) => <b>{v}</b> },
                { title: 'Обращений', dataIndex: 'count', align: 'right', sorter: (a, b) => a.count - b.count },
                { title: 'Индекс настроения', dataIndex: 'mood_index', align: 'right', sorter: (a, b) => a.mood_index - b.mood_index,
                  render: (v) => <span style={{ color: v < -30 ? C.brick : v > 10 ? C.green : C.text }}>{v > 0 ? '+' : ''}{Math.round(v)}</span> },
                { title: 'Решено', dataIndex: 'resolved_share', align: 'right', render: (v) => `${v}%`, sorter: (a, b) => a.resolved_share - b.resolved_share },
                { title: <Tooltip title="Среднее время от публикации обращения до передачи в подразделение">До передачи</Tooltip>, dataIndex: 'avg_hours_to_transfer', align: 'right', render: fmtHours },
                { title: 'До решения', dataIndex: 'avg_hours_to_resolve', align: 'right', render: fmtHours },
                { title: 'Открытых проблем', dataIndex: 'open_problems', align: 'right', render: (v, r) => <>{v}{r.high_problems > 0 && <span style={{ color: C.brick }}> ({r.high_problems} выс.)</span>}</> },
                { title: 'Срочных', dataIndex: 'urgent', align: 'right' },
                { title: 'Рейтинг', dataIndex: 'rating', align: 'right', defaultSortOrder: undefined, sorter: (a, b) => a.rating - b.rating, render: (v) => <span className="figure" style={{ fontSize: 14 }}>{v}</span> },
              ]} />
          </div>
        </>
      )}
      <DeptDrawer dept={selected} onClose={() => setSelected(null)}
        openFeed={(code) => nav(`/feed?${toSearch({ ...filters, department: code })}`)}
        openProblem={(id) => setSp((p) => { const n = new URLSearchParams(p); n.set('problem', String(id)); return n })} />
    </>
  )
}

function DeptDrawer({ dept, onClose, openFeed, openProblem }: { dept: Dept | null; onClose: () => void; openFeed: (c: string) => void; openProblem: (id: number) => void }) {
  const { deptName } = useApp()
  const { data: clusters } = useQuery({
    queryKey: ['clusters', 'dept', dept?.code], enabled: !!dept,
    queryFn: () => api.get<Paged<Cluster>>('/api/clusters', { department: dept!.code, status: 'new,transferred,in_progress', page_size: 10 }),
  })
  const { data: digest, isFetching } = useQuery({
    queryKey: ['digest', dept?.code], enabled: !!dept,
    queryFn: () => api.get<{ text: string; model: string; total: number }>('/api/assistant/digest', { department: dept!.code, days: 7 }),
  })
  return (
    <Drawer open={!!dept} onClose={() => { onClose() }} size={620} title={dept ? deptName(dept.code) : ''}
      extra={dept && <Button type="primary" onClick={() => { const c = dept.code; onClose(); openFeed(c) }}>Обращения подразделения</Button>}>
      {dept && (
        <>
          <div className="kpis" style={{ gridTemplateColumns: 'repeat(3, minmax(0,1fr))', marginTop: 0 }}>
            <div className="kpi"><span className="kpi-label">Обращений</span><span className="figure kpi-value">{dept.count}</span></div>
            <div className="kpi"><span className="kpi-label">Индекс настроения</span><span className="figure kpi-value">{Math.round(dept.mood_index)}</span></div>
            <div className="kpi"><span className="kpi-label">Решено</span><span className="figure kpi-value">{dept.resolved_share}%</span></div>
          </div>
          <div className="section-label">Дайджест за неделю</div>
          {isFetching ? <Skeleton active /> : <div className="chat-answer" style={{ fontSize: 14.5 }}>{digest?.text}</div>}
          {digest && <div className="muted" style={{ fontSize: 12 }}>Сформировано: {digest.model}</div>}
          <div className="section-label">Открытые проблемы</div>
          {clusters?.items.length ? clusters.items.map((c) => <ProblemRow key={c.id} c={c} onOpen={(id) => { onClose(); openProblem(id) }} />)
            : <Empty title="Открытых проблем нет" />}
        </>
      )}
    </Drawer>
  )
}
