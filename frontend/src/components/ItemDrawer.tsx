import { CheckOutlined, DeleteOutlined, EnvironmentOutlined, EyeOutlined, LinkOutlined, LockOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Divider, Drawer, Input, Popconfirm, Select, Skeleton, Space, Tag, Timeline, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../context'
import { GEO_LABEL, LANG_LABEL, PII_LABEL, SENT_LABEL, STATUS_LABEL, TYPE_LABEL } from '../theme'
import type { ItemDetail } from '../types'
import { Confidence, fmtDate, GeoTag, MaskedText, PlatformTag, PriorityTag, SentimentTag, StatusTag, UrgencyTags } from './ui'

const FIELD_LABEL: Record<string, string> = { department: 'Подразделение', sentiment: 'Тональность', message_type: 'Тип', status: 'Статус', geo: 'Геопривязка' }
const EVIDENCE_LABEL: Record<string, string> = { city: 'название города', landmarks: 'объекты города', streets: 'улицы', suburbs: 'пригороды', region: 'область', other: 'другие места' }

export default function ItemDrawer() {
  const [sp, setSp] = useSearchParams()
  const id = sp.get('item')
  const close = () => setSp((p) => { const n = new URLSearchParams(p); n.delete('item'); return n })
  const openProblem = (cid: number) => setSp((p) => { const n = new URLSearchParams(p); n.delete('item'); n.set('problem', String(cid)); return n })
  const { can, deptName, meta } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [original, setOriginal] = useState<string | null>(null)
  const [edit, setEdit] = useState<{ department?: string; sentiment?: string; message_type?: string; comment?: string }>({})
  const [reply, setReply] = useState('')

  const { data: it, isLoading, error } = useQuery({
    queryKey: ['item', id], queryFn: () => api.get<ItemDetail>(`/api/items/${id}`), enabled: !!id,
  })
  useEffect(() => { setOriginal(null); setEdit({}); setReply('') }, [id])

  const refresh = (d?: ItemDetail) => {
    if (d) qc.setQueryData(['item', id], d)
    qc.invalidateQueries({ queryKey: ['items'] })
    qc.invalidateQueries({ queryKey: ['overview'] })
    qc.invalidateQueries({ queryKey: ['ops'] })
  }
  const correct = useMutation({
    mutationFn: (body: object) => api.patch<ItemDetail>(`/api/items/${id}`, body),
    onSuccess: (d) => { refresh(d); setEdit({}); message.success('Изменения сохранены и записаны в журнал') },
    onError: (e: Error) => message.error(e.message),
  })
  const confirm = useMutation({
    mutationFn: () => api.post(`/api/items/${id}/confirm`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['item', id] }); refresh(); message.success('Результат ИИ подтверждён') },
    onError: (e: Error) => message.error(e.message),
  })
  const reanalyze = useMutation({
    mutationFn: () => api.post<ItemDetail>(`/api/items/${id}/reanalyze`),
    onSuccess: (d) => { refresh(d); message.success('Обращение проанализировано заново') },
    onError: (e: Error) => message.error(e.message),
  })
  const send = useMutation({
    mutationFn: () => api.post(`/api/items/${id}/reply`, { text: reply }),
    onSuccess: () => { setReply(''); qc.invalidateQueries({ queryKey: ['item', id] }); message.success('Ответ отправлен жителю') },
    onError: (e: Error) => message.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => api.del(`/api/items/${id}`),
    onSuccess: () => { refresh(); close(); message.success('Обращение удалено') },
    onError: (e: Error) => message.error(e.message),
  })
  const geoDecide = useMutation({
    mutationFn: (status: string) => api.post<ItemDetail>(`/api/items/${id}/geo`, { status }),
    onSuccess: (d) => { refresh(d); message.success('Геопривязка сохранена') },
    onError: (e: Error) => message.error(e.message),
  })
  const showOriginal = async () => {
    try { setOriginal((await api.get<{ text: string }>(`/api/items/${id}/original`)).text) }
    catch (e) { message.error((e as Error).message) }
  }

  const e = it?.enrichment
  const dirty = Object.keys(edit).some((k) => k !== 'comment' && edit[k as keyof typeof edit])

  return (
    <Drawer open={!!id} onClose={close} size={640} destroyOnHidden
      title={it ? <span>Обращение №{it.id}{it.is_direct && <Tag color="purple" style={{ marginLeft: 8 }}><LockOutlined /> Direct</Tag>}</span> : 'Обращение'}
      extra={it?.url && <Button href={it.url} target="_blank" rel="noreferrer" icon={<LinkOutlined />}>Оригинал</Button>}>
      {isLoading && <Skeleton active paragraph={{ rows: 10 }} />}
      {error && <Alert type="error" showIcon title={(error as Error).message} />}
      {it && (
        <>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
            <PlatformTag value={it.platform} kind={it.kind} /><GeoTag value={it.geo_status} reviewed={it.geo_reviewed} />
            {it.parent_url && <a href={it.parent_url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>Открыть исходный пост</a>}
          </div>
          <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
            {it.source_name}{it.is_synthetic && <Tag style={{ marginLeft: 6 }}>демо-данные</Tag>} · {fmtDate(it.published_at)} · {LANG_LABEL[it.lang ?? 'other']}
            {it.author && <> · автор #{it.author}</>}
            {(it.reactions > 0 || it.views > 0) && <> · реакций {it.reactions}, просмотров {it.views}</>}
          </div>
          {it.is_direct && (
            <Alert type="info" showIcon style={{ marginBottom: 12 }} title="Личное обращение в официальный аккаунт"
              description="Показан текст с маскированными персональными данными. Просмотр оригинала доступен оператору и записывается в журнал доступа." />
          )}
          <div className="panel" style={{ background: '#FAFBFC' }}>
            <MaskedText text={original ?? it.text} />
            {it.pii_found.length > 0 && !original && (
              <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
                Скрыто: {it.pii_found.map((k) => PII_LABEL[k] ?? k).join(', ')}
              </div>
            )}
            {it.can_view_original && !original && it.pii_found.length > 0 && (
              <Button size="small" icon={<EyeOutlined />} style={{ marginTop: 8 }} onClick={showOriginal}>
                Показать оригинал (запишется в журнал)
              </Button>
            )}
            {original && <Tag color="gold" style={{ marginTop: 8 }}>Оригинал — просмотр записан в журнал</Tag>}
          </div>

          {it.context_text && (
            <div className="muted" style={{ fontSize: 13, marginTop: 10, borderLeft: '3px solid #DDE3EA', paddingLeft: 10 }}>
              Комментарий к посту: <MaskedText text={it.context_text.slice(0, 300) + (it.context_text.length > 300 ? '…' : '')} />
            </div>
          )}
          <div className="panel" style={{ marginTop: 12, padding: '10px 14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span><EnvironmentOutlined /> <b>{GEO_LABEL[it.geo_status]}</b>{it.geo_reviewed && <span className="muted"> · решение оператора</span>}</span>
              {can('operator') && (
                <span style={{ display: 'flex', gap: 6 }}>
                  <Button size="small" disabled={it.geo_status === 'local' && it.geo_reviewed} loading={geoDecide.isPending && geoDecide.variables === 'local'} onClick={() => geoDecide.mutate('local')}>Павлодар</Button>
                  <Button size="small" disabled={it.geo_status === 'not_local' && it.geo_reviewed} loading={geoDecide.isPending && geoDecide.variables === 'not_local'} onClick={() => geoDecide.mutate('not_local')}>Не Павлодар</Button>
                </span>
              )}
            </div>
            <div style={{ fontSize: 13, marginTop: 4 }}>{it.geo_reason}</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              {Object.entries(it.geo_evidence ?? {}).filter(([k, v]) => EVIDENCE_LABEL[k] && Array.isArray(v) && v.length)
                .map(([k, v]) => `${EVIDENCE_LABEL[k]}: ${(v as string[]).join(', ')}`).join(' · ')}
              {it.geo_llm && ` · модель: ${GEO_LABEL[it.geo_llm] ?? it.geo_llm}${it.place_mentioned ? ` (${it.place_mentioned})` : ''}`}
            </div>
          </div>

          {it.is_spam && <Alert type="warning" showIcon style={{ marginTop: 12 }} title={`Отмечено как спам: ${it.spam_reason ?? ''}`} />}
          {it.duplicate_of_id && <Alert type="info" showIcon style={{ marginTop: 12 }} title={`Дубликат обращения №${it.duplicate_of_id}`} />}

          {e && (
            <>
              <div className="section-label">Анализ ИИ (рекомендация, решение принимает сотрудник)</div>
              {e.needs_review && <Alert type="warning" showIcon style={{ marginBottom: 10 }}
                title="Низкая уверенность — требует проверки" description="Подтвердите результат или исправьте подразделение." />}
              <dl className="dl">
                <dt>Подразделение</dt>
                <dd>
                  <b>{deptName(e.primary_department)}</b> <Confidence value={e.dept_confidence} />
                  {e.departments.length > 1 && <div className="muted" style={{ fontSize: 13 }}>Также: {e.departments.slice(1).map(deptName).join(', ')}</div>}
                  {e.corrected && <div style={{ fontSize: 12.5 }}><Tag color="blue">исправлено</Tag>модель предлагала: {deptName(e.model_department)}</div>}
                </dd>
                <dt>Тональность</dt><dd><SentimentTag value={e.sentiment} score={e.sentiment_score} /></dd>
                <dt>Тип</dt><dd>{TYPE_LABEL[e.message_type]}</dd>
                {e.urgency_markers.length > 0 && <><dt>Срочность</dt><dd><UrgencyTags markers={e.urgency_markers} /></dd></>}
                {e.problem_type && <><dt>Проблема</dt><dd>{e.problem_type}</dd></>}
                {(e.district || e.address || e.object) && <><dt>Место / объект</dt><dd>{[e.district, e.address, e.object].filter(Boolean).join(', ')}</dd></>}
                <dt>Обоснование</dt><dd style={{ lineHeight: 1.5 }}>{e.rationale}</dd>
                {it.cluster && <><dt>Проблема (кластер)</dt><dd>
                  <a onClick={() => openProblem(it.cluster!.id)}>{it.cluster.title}</a> <PriorityTag value={it.cluster.priority} /></dd></>}
                <dt>Статус</dt><dd><StatusTag value={it.status} /></dd>
              </dl>
              <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                Модель: {e.model}{e.model.startsWith('rules') ? ' (резервный анализ по правилам, без LLM)' : ''} · промпт {e.prompt_version}
                {e.latency_ms != null && <> · {e.latency_ms} мс</>}
                {e.reviewed && e.reviewed_at && <> · проверено {fmtDate(e.reviewed_at)}</>}
              </div>
            </>
          )}

          {can('operator') && e && (
            <>
              <Divider style={{ margin: '18px 0 12px' }} />
              <div className="section-label" style={{ marginTop: 0 }}>Проверка и исправление</div>
              <Space wrap style={{ marginBottom: 8 }}>
                <Select style={{ width: 210 }} placeholder="Подразделение" value={edit.department ?? e.primary_department}
                  onChange={(v) => setEdit({ ...edit, department: v === e.primary_department ? undefined : v })}
                  options={meta?.departments.map((d) => ({ value: d.code, label: d.name }))} aria-label="Подразделение" />
                <Select style={{ width: 160 }} value={edit.sentiment ?? e.sentiment} aria-label="Тональность"
                  onChange={(v) => setEdit({ ...edit, sentiment: v === e.sentiment ? undefined : v })}
                  options={Object.entries(SENT_LABEL).map(([value, label]) => ({ value, label }))} />
                <Select style={{ width: 150 }} value={edit.message_type ?? e.message_type} aria-label="Тип"
                  onChange={(v) => setEdit({ ...edit, message_type: v === e.message_type ? undefined : v })}
                  options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} />
              </Space>
              <Input.TextArea rows={2} placeholder="Комментарий к исправлению (необязательно)" value={edit.comment}
                onChange={(ev) => setEdit({ ...edit, comment: ev.target.value })} maxLength={500} />
              <Space wrap style={{ marginTop: 10 }}>
                <Button type="primary" disabled={!dirty} loading={correct.isPending} onClick={() => correct.mutate(edit)}>
                  Сохранить исправление
                </Button>
                <Button icon={<CheckOutlined />} disabled={dirty || e.reviewed} loading={confirm.isPending} onClick={() => confirm.mutate()}>
                  {e.reviewed ? 'Проверено' : 'Подтвердить результат ИИ'}
                </Button>
                <Tooltip title="Запустить анализ заново с текущим промптом и примерами исправлений">
                  <Button icon={<ReloadOutlined />} loading={reanalyze.isPending} onClick={() => reanalyze.mutate()}>Анализировать заново</Button>
                </Tooltip>
              </Space>
              <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="muted" style={{ fontSize: 13.5 }}>Статус обращения:</span>
                <Select style={{ width: 210 }} value={it.status} aria-label="Статус обращения"
                  onChange={(v) => correct.mutate({ status: v })}
                  options={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))} />
              </div>
            </>
          )}

          {can('operator') && it.can_reply && (
            <>
              <Divider style={{ margin: '18px 0 12px' }} />
              <div className="section-label" style={{ marginTop: 0 }}>Ответ жителю через бот</div>
              <Input.TextArea rows={3} value={reply} onChange={(ev) => setReply(ev.target.value)} maxLength={2000}
                placeholder="Ваше обращение передано в отдел ЖКХ. Ремонт теплотрассы запланирован на…" />
              <Popconfirm title="Отправить ответ жителю?" description="Сообщение уйдёт от имени акимата." okText="Отправить" cancelText="Отмена"
                onConfirm={() => send.mutate()} disabled={reply.trim().length < 2}>
                <Button type="primary" icon={<SendOutlined />} style={{ marginTop: 8 }} disabled={reply.trim().length < 2} loading={send.isPending}>
                  Отправить ответ
                </Button>
              </Popconfirm>
            </>
          )}

          {it.corrections.length > 0 && (
            <>
              <div className="section-label">История изменений</div>
              <Timeline items={it.corrections.map((c) => ({
                content: <span style={{ fontSize: 13.5 }}>{fmtDate(c.at)} — {FIELD_LABEL[c.field] ?? c.field}: {label(c.field, c.old, deptName)} → <b>{label(c.field, c.new, deptName)}</b>{c.comment && <span className="muted"> ({c.comment})</span>}</span>,
              }))} />
            </>
          )}

          {can('admin') && (
            <div style={{ marginTop: 24 }}>
              <Popconfirm title="Удалить обращение по запросу?" description="Удаляются текст, анализ и связи с проблемами. Действие записывается в журнал."
                okText="Удалить" okButtonProps={{ danger: true }} cancelText="Отмена" onConfirm={() => remove.mutate()}>
                <Button danger type="text" icon={<DeleteOutlined />}>Удалить по запросу (п. 5.6)</Button>
              </Popconfirm>
            </div>
          )}
        </>
      )}
    </Drawer>
  )
}

function label(field: string, v: string | null, deptName: (c: string) => string) {
  if (!v) return '—'
  if (field === 'department') return deptName(v)
  if (field === 'sentiment') return SENT_LABEL[v] ?? v
  if (field === 'message_type') return TYPE_LABEL[v] ?? v
  if (field === 'status') return STATUS_LABEL[v] ?? v
  if (field === 'geo') return GEO_LABEL[v] ?? v
  return v
}
