import { UnorderedListOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Drawer, Select, Skeleton, Space, Tag, Tooltip } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../context'
import { C, PRIO_COLOR, STATUS_LABEL } from '../theme'
import type { ClusterDetail } from '../types'
import Chart from './Chart'
import { ExportMenu, fmtDate, fmtShort, MaskedText, PlatformTag, PriorityTag, SentimentTag, StatusTag, UrgencyTags } from './ui'

export function PriorityBreakdown({ c }: { c: ClusterDetail | import('../types').Cluster }) {
  const f = c.priority_factors
  if (!f?.terms) return null
  return (
    <div>
      {Object.entries(f.terms).map(([k, t]) => (
        <div className="factor" key={k}>
          <span>{t.label} <span className="muted">({String(t.value)})</span></span>
          <span className="factor-track"><i style={{ width: `${(t.points / t.max) * 100}%`, background: PRIO_COLOR[c.priority] }} /></span>
          <span style={{ textAlign: 'right' }}>{t.points}<span className="muted">/{t.max}</span></span>
        </div>
      ))}
      <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
        Итого {f.score} баллов. Высокий ≥ {f.thresholds.high}, средний ≥ {f.thresholds.medium}.
        {f.forced_by_life_threat && ' Приоритет повышен до высокого из-за угрозы жизни.'}
      </div>
    </div>
  )
}

export default function ClusterDrawer() {
  const [sp, setSp] = useSearchParams()
  const id = sp.get('problem')
  const nav = useNavigate()
  const { can, meta } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const close = () => setSp((p) => { const n = new URLSearchParams(p); n.delete('problem'); return n })
  const openItem = (iid: number) => setSp((p) => { const n = new URLSearchParams(p); n.delete('problem'); n.set('item', String(iid)); return n })

  const { data: c, isLoading, error } = useQuery({
    queryKey: ['cluster', id], queryFn: () => api.get<ClusterDetail>(`/api/clusters/${id}`), enabled: !!id,
  })
  const update = useMutation({
    mutationFn: (body: object) => api.patch<ClusterDetail>(`/api/clusters/${id}`, body),
    onSuccess: (d) => {
      qc.setQueryData(['cluster', id], d)
      ;['clusters', 'overview', 'items', 'departments'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
      message.success('Проблема обновлена, обращения переведены в новый статус')
    },
    onError: (e: Error) => message.error(e.message),
  })

  return (
    <Drawer open={!!id} onClose={close} size={720} destroyOnHidden title={c ? `Проблема №${c.id}` : 'Проблема'}
      extra={c && <Space>
        <ExportMenu base="/api/export/items" params={{ cluster_id: String(c.id), days: '3650' }} label="Обращения" />
        <Button icon={<UnorderedListOutlined />} onClick={() => nav(`/feed?cluster_id=${c.id}&days=3650`)}>В ленте</Button>
      </Space>}>
      {isLoading && <Skeleton active paragraph={{ rows: 12 }} />}
      {error && <Alert type="error" showIcon title={(error as Error).message} />}
      {c && (
        <>
          <h2 style={{ margin: '0 0 6px', fontSize: 20, lineHeight: 1.3 }}>{c.title}</h2>
          <Button type="primary" style={{ margin: '10px 0 16px' }} onClick={() => setSp(p => { const n = new URLSearchParams(p); n.delete('problem'); n.set('decision', String(c.id)); return n })}>Подготовить данные для решения</Button>
          <Space wrap size={6} style={{ marginBottom: 10 }}>
            <PriorityTag value={c.priority} score={c.priority_score} />
            <StatusTag value={c.status} />
            <Tag>{c.department_name}</Tag>
            {c.district && <Tag>{c.district}</Tag>}
            {c.is_hot && <Tag color="volcano">Горячая тема: рост за 24 ч</Tag>}
            {c.multi_platform && <Tag color="geekblue">Обсуждают на {c.platforms.filter((p) => !['demo', 'upload'].includes(p)).length} платформах</Tag>}
          </Space>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {c.platforms.map((p) => <PlatformTag key={p} value={p} />)}
            <span className="muted" style={{ fontSize: 12.5 }}>{c.source_count} источн.</span>
          </div>
          <p style={{ lineHeight: 1.55, margin: '0 0 4px' }}>{c.summary}</p>
          <div className="muted" style={{ fontSize: 12.5 }}>
            {c.item_count} обращ. · первое {fmtDate(c.first_seen)} · последнее {fmtDate(c.last_seen)}
            {c.summary_model && <> · резюме: {c.summary_model === 'extractive' ? 'без LLM (выдержка)' : c.summary_model}</>}
          </div>

          {can('operator') && (
            <div className="panel" style={{ marginTop: 14, background: '#FAFBFC' }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>Маршрутизация</div>
              <Space wrap>
                <Select style={{ width: 230 }} value={c.department} aria-label="Ответственное подразделение"
                  onChange={(v) => update.mutate({ department: v })}
                  options={meta?.departments.map((d) => ({ value: d.code, label: d.name }))} />
                <Select style={{ width: 220 }} value={c.status} aria-label="Статус проблемы"
                  onChange={(v) => update.mutate({ status: v })}
                  options={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))} />
                {c.status === 'new' && (
                  <Button type="primary" loading={update.isPending} onClick={() => update.mutate({ status: 'transferred' })}>
                    Передать в подразделение
                  </Button>
                )}
              </Space>
            </div>
          )}

          <div className="section-label">Почему такой приоритет</div>
          <PriorityBreakdown c={c} />

          {c.timeline.length > 1 && (
            <>
              <div className="section-label">Динамика обращений</div>
              <Chart height={140} option={{
                grid: { left: 4, right: 8, top: 10, bottom: 4, containLabel: true },
                xAxis: { type: 'category', data: c.timeline.map((t) => t.date.slice(5).split('-').reverse().join('.')), axisTick: { show: false } },
                yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#EEF1F4' } } },
                tooltip: { trigger: 'axis' },
                series: [{ type: 'bar', data: c.timeline.map((t) => t.count), itemStyle: { color: C.sky, borderRadius: [3, 3, 0, 0] }, barMaxWidth: 22, name: 'Обращений' }],
              }} />
            </>
          )}

          <div className="section-label">Обращения ({c.items.length}{c.hidden_direct ? ` + ${c.hidden_direct} личных, скрыты для вашей роли` : ''})</div>
          {c.items.map((it) => (
            <div key={it.id} className="prob" style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }} onClick={() => openItem(it.id)}
              role="button" tabIndex={0} onKeyDown={(ev) => ev.key === 'Enter' && openItem(it.id)}>
              <div>
                <MaskedText text={it.text} clamp />
                <div className="prob-meta" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                  <PlatformTag value={it.platform} kind={it.kind} />
                  {fmtShort(it.published_at)} · {it.source_name}{it.is_direct && ' · Direct'}
                  {it.url && <a href={it.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>оригинал</a>}
                  {it.enrichment?.urgency_markers?.length ? <> · <UrgencyTags markers={it.enrichment.urgency_markers} /></> : null}
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <SentimentTag value={it.enrichment?.sentiment} />
                {it.similarity !== undefined && <Tooltip title="Сходство с центром кластера"><div className="muted" style={{ fontSize: 12 }}>{Math.round(it.similarity * 100)}%</div></Tooltip>}
              </div>
            </div>
          ))}
          {c.copies?.length > 0 && (
            <>
              <div className="section-label">Те же тексты в других источниках ({c.copies.length})</div>
              {c.copies.map((x) => (
                <div key={x.id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, padding: '4px 0' }}>
                  <PlatformTag value={x.platform} /> {x.source_name} · {fmtShort(x.published_at)} · копия №{x.duplicate_of_id}
                  {x.url && <a href={x.url} target="_blank" rel="noreferrer">оригинал</a>}
                </div>
              ))}
            </>
          )}
        </>
      )}
    </Drawer>
  )
}
