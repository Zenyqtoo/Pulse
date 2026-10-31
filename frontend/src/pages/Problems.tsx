import { ReloadOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Segmented, Select, Switch, Table, Tag, Tooltip } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import FilterBar from '../components/FilterBar'
import { Empty, ExportMenu, fmtShort, PageHead, PlatformTag, PriorityTag } from '../components/ui'
import { useApp } from '../context'
import { useFilters } from '../filters'
import { C, STATUS_LABEL } from '../theme'
import type { Cluster, Paged } from '../types'

export default function Problems() {
  const { filters } = useFilters()
  const [, setSp] = useSearchParams()
  const { can } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [sort, setSort] = useState('priority')
  const [hot, setHot] = useState(false)
  const [multi, setMulti] = useState(false)
  const [page, setPage] = useState(1)
  const params = { department: filters.department, priority: filters.priority, status: filters.status, district: filters.district,
    q: filters.q, hot: hot || undefined, platform: filters.platform, multi: multi || undefined, sort, page, page_size: 20 }
  const { data, isLoading, error } = useQuery({ queryKey: ['clusters', params], queryFn: () => api.get<Paged<Cluster>>('/api/clusters', params) })
  const open = (id: number) => setSp((p) => { const n = new URLSearchParams(p); n.set('problem', String(id)); return n })
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api.patch(`/api/clusters/${id}`, { status }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['clusters'] }); qc.invalidateQueries({ queryKey: ['overview'] }); message.success('Статус обновлён') },
    onError: (e: Error) => message.error(e.message),
  })
  const recluster = useMutation({
    mutationFn: () => api.post<{ clusters: number }>('/api/clusters/recluster'),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['clusters'] }); message.success(`Проблемы пересобраны: ${r.clusters}`) },
    onError: (e: Error) => message.error(e.message),
  })

  return (
    <>
      <PageHead title="Проблемы и приоритеты" sub="Похожие обращения, объединённые в проблемы. Приоритет считается по прозрачной формуле — откройте проблему, чтобы увидеть разбор."
        extra={<>
          {can('operator') && <Button icon={<ReloadOutlined />} loading={recluster.isPending} onClick={() => recluster.mutate()}>Пересобрать</Button>}
          <ExportMenu base="/api/export/clusters" params={{ department: filters.department, priority: filters.priority, status: filters.status }} />
        </>} />
      <FilterBar fields={['q', 'platform', 'department', 'priority', 'status', 'district']} />
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <Segmented value={sort} onChange={(v) => { setSort(v as string); setPage(1) }} options={[
          { value: 'priority', label: 'По приоритету' }, { value: 'count', label: 'По числу обращений' },
          { value: 'growth', label: 'По росту за 24 ч' }, { value: 'recent', label: 'Сначала новые' }]} />
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
          <Switch size="small" checked={hot} onChange={(v) => { setHot(v); setPage(1) }} /> Только горячие темы за 24 ч
        </span>
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
          <Switch size="small" checked={multi} onChange={(v) => { setMulti(v); setPage(1) }} /> Только на нескольких платформах
        </span>
      </div>
      {error && <Alert type="error" showIcon title={(error as Error).message} />}
      <div className="panel" style={{ padding: 0 }}>
        <Table<Cluster> rowKey="id" loading={isLoading} dataSource={data?.items} size="middle"
          scroll={{ x: 960 }}
          locale={{ emptyText: <Empty title="Проблем не найдено">Измените фильтры или дождитесь анализа новых обращений.</Empty> }}
          onRow={(r) => ({ onClick: () => open(r.id), style: { cursor: 'pointer' } })}
          pagination={{ current: page, pageSize: 20, total: data?.total, onChange: setPage, showSizeChanger: false, showTotal: (t) => `Всего ${t}` }}
          columns={[
            { title: 'Приоритет', dataIndex: 'priority', width: 120, render: (_, r) => <PriorityTag value={r.priority} score={r.priority_score} /> },
            { title: 'Проблема', dataIndex: 'title', render: (_, r) => (
              <div>
                <div style={{ fontWeight: 700 }}>{r.title}</div>
                <div className="muted msg-clamp" style={{ fontSize: 13 }}>{r.summary}</div>
                <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {r.platforms.filter((p) => !['demo', 'upload'].includes(p)).map((p) => <PlatformTag key={p} value={p} />)}
                  {r.has_urgent && <Tag color="red">срочно</Tag>}
                  {r.is_hot && <Tag color="volcano">растёт</Tag>}
                  {r.district && <Tag>{r.district}</Tag>}
                </div>
              </div>) },
            { title: 'Подразделение', dataIndex: 'department_name', width: 160 },
            { title: 'Обращений', dataIndex: 'item_count', width: 105, align: 'right', render: (v) => <span className="figure" style={{ fontSize: 15 }}>{v}</span> },
            { title: '24 ч', dataIndex: 'count_24h', width: 90, align: 'right', render: (_, r) => (
              <Tooltip title={`За последние сутки ${r.count_24h}, за предыдущие ${r.count_prev_24h}`}>
                <span style={{ color: r.count_24h > r.count_prev_24h ? C.brick : C.muted }}>{r.count_24h ? `+${r.count_24h}` : '0'}</span>
              </Tooltip>) },
            { title: 'Негатив', dataIndex: 'neg_share', width: 90, align: 'right', render: (v) => `${Math.round(v * 100)}%` },
            { title: 'Статус', dataIndex: 'status', width: 200, render: (v, r) => can('operator')
              ? <span onClick={(e) => e.stopPropagation()}><Select size="small" value={v} style={{ width: 180 }} aria-label="Статус"
                  onChange={(status) => setStatus.mutate({ id: r.id, status })}
                  options={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))} /></span>
              : STATUS_LABEL[v] },
            { title: 'Последнее', dataIndex: 'last_seen', width: 110, render: fmtShort },
          ]} />
      </div>
    </>
  )
}
