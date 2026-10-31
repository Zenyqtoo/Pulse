import { CheckOutlined, CloseOutlined, EnvironmentOutlined, LockOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Select, Switch, Table, Tag, Tooltip } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import FilterBar from '../components/FilterBar'
import { Confidence, Empty, ExportMenu, fmtShort, GeoTag, MaskedText, PageHead, PlatformTag, PriorityTag, SentimentTag, StatusTag, UrgencyTags } from '../components/ui'
import { useApp } from '../context'
import { useFilters } from '../filters'
import { TYPE_LABEL } from '../theme'
import type { Item, Paged } from '../types'

type Mode = 'all' | 'review' | 'direct' | 'geo'
const COPY: Record<Mode, { title: string; sub: string }> = {
  all: { title: 'Лента обращений', sub: 'Все проанализированные обращения из подключённых источников. Нажмите на строку, чтобы открыть карточку.' },
  review: { title: 'Проверка ИИ', sub: 'Обращения, где уверенность модели ниже порога. Подтвердите результат или исправьте — исправления становятся примерами для модели.' },
  geo: { title: 'Проверка геопривязки', sub: 'Сообщения, которые могут касаться Павлодара, но место не ясно. Решение оператора включает сообщение в аналитику или исключает его. В основную аналитику попадает только «Павлодар».' },
  direct: { title: 'Личные обращения (Direct)', sub: 'Сообщения жителей в официальные аккаунты акимата. Тексты показаны с маскированными персональными данными; каждый просмотр оригинала записывается в журнал.' },
}

export default function Feed({ mode }: { mode: Mode }) {
  const { filters } = useFilters()
  const [, setSp] = useSearchParams()
  const { can, deptName } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [sort, setSort] = useState(mode === 'review' ? 'confidence_asc' : 'date_desc')
  const [spam, setSpam] = useState(false)
  const [geoView, setGeoView] = useState('local')
  const key = JSON.stringify(filters)
  useEffect(() => setPage(1), [key, mode])

  const params = useMemo(() => ({
    ...filters,
    ...(mode === 'review' ? { needs_review: 'true', days: filters.date_from ? undefined : filters.days === '30' ? '3650' : filters.days } : {}),
    ...(mode === 'direct' ? { is_direct: 'true' } : {}),
    ...(mode === 'geo' ? { geo: 'possible', days: filters.date_from ? undefined : filters.days === '30' ? '3650' : filters.days }
      : { geo: geoView === 'local' ? undefined : geoView }),
    include_spam: spam || undefined, sort, page, page_size: pageSize,
  }), [filters, mode, spam, sort, page, pageSize, geoView])

  const { data, isLoading, error } = useQuery({ queryKey: ['items', params], queryFn: () => api.get<Paged<Item>>('/api/items', params) })
  const open = (id: number) => setSp((p) => { const n = new URLSearchParams(p); n.set('item', String(id)); return n })
  const confirm = useMutation({
    mutationFn: (id: number) => api.post(`/api/items/${id}/confirm`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['items'] }); qc.invalidateQueries({ queryKey: ['ops'] }); message.success('Результат ИИ подтверждён') },
    onError: (e: Error) => message.error(e.message),
  })
  const decide = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api.post(`/api/items/${id}/geo`, { status }),
    onSuccess: (_, v) => {
      ['items', 'ops', 'overview', 'clusters'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
      message.success(v.status === 'local' ? 'Включено в аналитику Павлодара' : 'Исключено из аналитики')
    },
    onError: (e: Error) => message.error(e.message),
  })
  const exportParams = Object.fromEntries(Object.entries(params).filter(([k]) => !['page', 'page_size', 'sort'].includes(k)).map(([k, v]) => [k, v === undefined ? undefined : String(v)]))

  return (
    <>
      <PageHead title={COPY[mode].title} sub={COPY[mode].sub}
        extra={<ExportMenu base="/api/export/items" params={exportParams} />} />
      <FilterBar />
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <span className="muted">{data ? `Найдено: ${data.total}` : ' '}</span>
        <Select value={sort} onChange={setSort} style={{ width: 230 }} aria-label="Сортировка" options={[
          { value: 'date_desc', label: 'Сначала новые' }, { value: 'date_asc', label: 'Сначала старые' },
          { value: 'confidence_asc', label: 'Сначала низкая уверенность' }, { value: 'sentiment_asc', label: 'Сначала самые негативные' },
          { value: 'reach_desc', label: 'По охвату' }]} />
        {can('operator') && mode === 'all' && (
          <Select value={geoView} onChange={(v) => { setGeoView(v); setPage(1) }} style={{ width: 230 }} aria-label="Геопривязка"
            options={[{ value: 'local', label: 'Только Павлодар' }, { value: 'possible', label: 'Возможно Павлодар' },
              { value: 'not_local', label: 'Исключённые (не Павлодар)' }, { value: 'all', label: 'Все сообщения' }]} />
        )}
        {can('operator') && mode === 'all' && (
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
            <Switch size="small" checked={spam} onChange={setSpam} /> Показать спам и дубликаты
          </span>
        )}
        {filters.cluster_id && <Tag closable onClose={() => setSp((p) => { const n = new URLSearchParams(p); n.delete('cluster_id'); return n })}>Проблема №{filters.cluster_id}</Tag>}
      </div>
      {error && <Alert type="error" showIcon title={(error as Error).message} style={{ marginBottom: 12 }} />}
      <div className="panel" style={{ padding: 0 }}>
        <Table<Item> rowKey="id" loading={isLoading} dataSource={data?.items} size="middle" scroll={{ x: 1100 }}
          onRow={(r) => ({ onClick: () => open(r.id), style: { cursor: 'pointer' } })}
          locale={{ emptyText: mode === 'review'
            ? <Empty title="Очередь проверки пуста">Все результаты ИИ выше порога уверенности или уже проверены оператором.</Empty>
            : mode === 'geo' ? <Empty title="Очередь геопривязки пуста">Все собранные сообщения однозначно отнесены к Павлодару или исключены.</Empty>
            : mode === 'direct' ? <Empty title="Личных обращений нет">Подключите бот приёма обращений на странице «Источники и сбор».</Empty>
            : <Empty title="Ничего не найдено">Измените фильтры или период.</Empty> }}
          pagination={{ current: page, pageSize, total: data?.total, showSizeChanger: true, pageSizeOptions: [25, 50, 100],
            onChange: (p, s) => { setPage(p); setPageSize(s) }, showTotal: (t) => `Всего ${t}` }}
          columns={[
            { title: 'Дата', dataIndex: 'published_at', width: 100, render: (v, r) => (
              <div style={{ fontSize: 13 }}>{fmtShort(v)}{r.is_direct && <div><Tag color="purple" style={{ marginTop: 4 }}><LockOutlined /> Direct</Tag></div>}</div>) },
            { title: 'Обращение', dataIndex: 'text', render: (v, r) => (
              <div style={{ maxWidth: 560 }}>
                <MaskedText text={v} clamp />
                <div className="muted" style={{ fontSize: 12.5, marginTop: 3, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                  <PlatformTag value={r.platform} kind={r.kind} />
                  {r.geo_status !== 'local' && <GeoTag value={r.geo_status} reviewed={r.geo_reviewed} />}
                  {r.source_name}{r.is_synthetic && ' (демо)'}{r.enrichment?.district && ` · ${r.enrichment.district}`}
                  {r.is_spam && <Tag color="default" style={{ marginLeft: 6 }}>спам</Tag>}
                  {r.duplicate_of_id && <Tag style={{ marginLeft: 6 }}>дубликат №{r.duplicate_of_id}</Tag>}
                  {r.enrichment && <> <UrgencyTags markers={r.enrichment.urgency_markers} /></>}
                </div>
                {mode === 'geo' && r.geo_reason && <div style={{ fontSize: 12.5, marginTop: 4 }}><EnvironmentOutlined /> {r.geo_reason}</div>}
              </div>) },
            { title: 'Подразделение', width: 190, render: (_, r) => r.enrichment ? (
              <div>
                <div style={{ fontWeight: 700, fontSize: 13.5 }}>{deptName(r.enrichment.primary_department)}{r.enrichment.corrected && <Tooltip title="Исправлено оператором"> ✎</Tooltip>}</div>
                <Confidence value={r.enrichment.dept_confidence} />
              </div>) : '—' },
            { title: 'Тональность', width: 140, render: (_, r) => <SentimentTag value={r.enrichment?.sentiment} score={r.enrichment?.sentiment_score} /> },
            { title: 'Тип', width: 120, render: (_, r) => r.enrichment ? TYPE_LABEL[r.enrichment.message_type] : '—' },
            { title: 'Проблема', width: 200, render: (_, r) => r.cluster ? (
              <div onClick={(e) => { e.stopPropagation(); setSp((p) => { const n = new URLSearchParams(p); n.set('problem', String(r.cluster!.id)); return n }) }}>
                <PriorityTag value={r.cluster.priority} />
                <div className="msg-clamp" style={{ fontSize: 12.5, marginTop: 3, color: '#1F7FC1' }}>{r.cluster.title}</div>
              </div>) : <span className="muted">—</span> },
            { title: 'Статус', dataIndex: 'status', width: 120, render: (v) => <StatusTag value={v} /> },
            ...(mode === 'geo' && can('operator') ? [{
              title: 'Решение', width: 220, render: (_: unknown, r: Item) => (
                <div style={{ display: 'flex', gap: 6 }} onClick={(e) => e.stopPropagation()}>
                  <Button size="small" type="primary" icon={<EnvironmentOutlined />} onClick={() => decide.mutate({ id: r.id, status: 'local' })}>Павлодар</Button>
                  <Button size="small" icon={<CloseOutlined />} onClick={() => decide.mutate({ id: r.id, status: 'not_local' })}>Не Павлодар</Button>
                </div>),
            }] : []),
            ...(mode === 'review' && can('operator') ? [{
              title: '', width: 130, render: (_: unknown, r: Item) => (
                <Button size="small" icon={<CheckOutlined />} onClick={(e) => { e.stopPropagation(); confirm.mutate(r.id) }}>Подтвердить</Button>),
            }] : []),
          ]} />
      </div>
    </>
  )
}
