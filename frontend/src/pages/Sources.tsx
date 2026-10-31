import {
  ApiOutlined, CheckCircleOutlined, CloudDownloadOutlined, DeleteOutlined, DisconnectOutlined, EditOutlined, HistoryOutlined,
  InboxOutlined, LinkOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, App, Badge, Button, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Select, Switch, Table, Tabs, Tag, Tooltip, Typography, Upload,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Empty, fmtDate, PageHead, Panel, PlatformTag } from '../components/ui'
import { useApp } from '../context'
import { SCOPE_LABEL } from '../theme'

interface Source {
  id: number; type: string; name: string; config: Record<string, unknown>; enabled: boolean; is_synthetic: boolean
  schedule_minutes: number; platform: string; platform_name: string; url: string | null; description: string | null
  geo_scope: string; recommended_key: string | null; last_run_at: string | null; last_success_at: string | null
  last_status: string | null; last_error: string | null; items: number; local_items: number; connection: string; auto: boolean
}
interface Collector { type: string; title: string; description: string; platform: string; fields: { key: string; label: string; type: string; default?: unknown; required?: boolean }[] }
interface Run { id: number; source_id: number; source: string; trigger: string; started_at: string; finished_at: string | null; status: string; fetched: number; new_items: number; duplicates: number; spam: number; not_local: number; error: string | null }
interface Recommended {
  key: string; type: string; platform: string; name: string; url: string; geo_scope: string; content: string; description: string
  relevance: string; verified: string; access: string; collection: string; added_source_id: number | null
}
interface Connection {
  platform: string; app_configured: boolean; connected: boolean; origin: string | null; username: string | null
  scopes: string[]; expires_at: string | null; expires_soon: boolean; redirect_uri: string
  capabilities: { name: string; status: string; needs: string }[]
}

const TRIGGER: Record<string, string> = { schedule: 'по расписанию', manual: 'вручную', upload: 'загрузка файла' }
const TABS = [
  { key: 'all', label: 'Все', platforms: null },
  { key: 'telegram', label: 'Telegram', platforms: ['telegram'] },
  { key: 'instagram', label: 'Instagram', platforms: ['instagram'] },
  { key: 'threads', label: 'Threads', platforms: ['threads'] },
  { key: 'news', label: 'Новости и RSS', platforms: ['news'] },
  { key: 'direct', label: 'Обращения жителей', platforms: ['direct', 'upload'] },
  { key: 'demo', label: 'Демо', platforms: ['demo'] },
]
const CONN: Record<string, { status: 'success' | 'error' | 'warning' | 'default' | 'processing'; text: string }> = {
  ok: { status: 'success', text: 'Работает' }, warning: { status: 'warning', text: 'Работает с предупреждениями' },
  error: { status: 'error', text: 'Ошибка' }, disabled: { status: 'default', text: 'Отключён' },
  never: { status: 'processing', text: 'Ещё не запускался' }, manual: { status: 'default', text: 'Загрузка файлов' },
}
const REC_STATUS: Record<string, { color: string; text: string }> = {
  accessible: { color: 'green', text: 'Доступен для сбора' }, check_on_first_run: { color: 'blue', text: 'Проверится первым запуском' },
  needs_credentials: { color: 'gold', text: 'Нужны ключи доступа' }, needs_permission: { color: 'orange', text: 'Нужно одобрение Meta' },
  unverified: { color: 'default', text: 'Не проверен' },
}
const CAP: Record<string, { color: string; text: string }> = {
  available: { color: 'green', text: 'Доступно' }, limited: { color: 'blue', text: 'С ограничениями' },
  app_review: { color: 'orange', text: 'Нужен App Review' }, not_possible: { color: 'red', text: 'Недоступно в API' },
  not_collected: { color: 'default', text: 'Не используется' },
}
const PLATFORM_FOR_TYPE: Record<string, string> = {
  telegram_web: 'telegram', telethon: 'telegram', instagram: 'instagram', threads: 'threads', news: 'news', telegram_bot: 'direct', demo: 'demo',
}

export default function Sources() {
  const { can } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [sp, setSp] = useSearchParams()
  const tab = sp.get('tab') ?? 'all'
  const [q, setQ] = useState('')
  const [statusF, setStatusF] = useState<string | undefined>()
  const [editing, setEditing] = useState<Source | 'new' | null>(null)
  const [history, setHistory] = useState<Source | null>(null)
  const [scope, setScope] = useState('unknown')

  const status = useQuery({ queryKey: ['pipeline'], queryFn: () => api.get<{ busy: boolean; pending: number }>('/api/pipeline/status'), refetchInterval: 4000 })
  const busy = status.data?.busy
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api.get<Source[]>('/api/sources'), refetchInterval: busy ? 4000 : 30000 })
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => api.get<Run[]>('/api/runs', { limit: 100 }), refetchInterval: busy ? 4000 : 30000 })
  const collectors = useQuery({ queryKey: ['collectors'], queryFn: () => api.get<Collector[]>('/api/collectors') })
  const recommended = useQuery({ queryKey: ['recommended'], queryFn: () => api.get<Recommended[]>('/api/sources/recommended') })
  const invalidate = () => ['sources', 'runs', 'pipeline', 'overview', 'items', 'clusters', 'meta', 'recommended', 'connect']
    .forEach((k) => qc.invalidateQueries({ queryKey: [k] }))

  useEffect(() => {
    const ok = sp.get('connected'), err = sp.get('connect_error')
    if (ok) message.success(`${ok === 'instagram' ? 'Instagram' : 'Threads'} подключён`)
    if (err) message.error(`Подключение не выполнено: ${err}`)
    if (ok || err) setSp((p) => { const n = new URLSearchParams(p); n.delete('connected'); n.delete('connect_error'); return n }, { replace: true })
  }, [sp, setSp, message])

  const run = useMutation({ mutationFn: (id: number) => api.post(`/api/sources/${id}/run`),
    onSuccess: () => { message.info('Сбор запущен. Журнал обновится автоматически.'); invalidate() }, onError: (e: Error) => message.error(e.message) })
  const process = useMutation({ mutationFn: () => api.post('/api/pipeline/process'),
    onSuccess: () => { message.info('Анализ очереди запущен'); invalidate() }, onError: (e: Error) => message.error(e.message) })
  const toggle = useMutation({ mutationFn: (s: Source) => api.patch(`/api/sources/${s.id}`, { enabled: !s.enabled }),
    onSuccess: invalidate, onError: (e: Error) => message.error(e.message) })
  const remove = useMutation({ mutationFn: (s: Source) => api.del(`/api/sources/${s.id}`),
    onSuccess: () => { message.success('Источник удалён вместе с его сообщениями'); invalidate() }, onError: (e: Error) => message.error(e.message) })
  const addRec = useMutation({ mutationFn: (key: string) => api.post(`/api/sources/recommended/${key}`),
    onSuccess: () => { message.success('Источник добавлен'); invalidate() }, onError: (e: Error) => message.error(e.message) })

  const tabDef = TABS.find((t) => t.key === tab) ?? TABS[0]
  const rows = useMemo(() => (sources.data ?? []).filter((s) =>
    (!tabDef.platforms || tabDef.platforms.includes(s.platform))
    && (!statusF || s.connection === statusF)
    && (!q || `${s.name} ${s.url ?? ''} ${s.description ?? ''} ${JSON.stringify(s.config)}`.toLowerCase().includes(q.toLowerCase()))),
  [sources.data, tabDef, statusF, q])
  const count = (t: (typeof TABS)[number]) => (sources.data ?? []).filter((s) => !t.platforms || t.platforms.includes(s.platform)).length
  const recRows = (recommended.data ?? []).filter((r) => !tabDef.platforms || tabDef.platforms.includes(r.platform))

  const upload = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('source_name', `Загрузка: ${file.name}`.slice(0, 200))
    fd.append('geo_scope', scope)
    try {
      const r = await api.post<{ rows: number; new_items: number; duplicates: number; spam: number; not_local: number; warnings: string[] }>('/api/upload', fd)
      message.success(`Строк: ${r.rows}. Новых: ${r.new_items}, дубликатов: ${r.duplicates}, спам: ${r.spam}, не Павлодар: ${r.not_local}. Идёт анализ…`)
      if (r.warnings.length) message.warning(r.warnings.slice(0, 3).join('; '))
      invalidate()
    } catch (e) { message.error((e as Error).message) }
    return false
  }

  return (
    <>
      <PageHead title="Источники и сбор" sub="Платформы и каналы, из которых собираются обращения о Павлодаре. Сбор идёт по расписанию и по кнопке; всё собранное проходит единый анализ и геофильтр."
        extra={<>
          {can('operator') && <Button icon={<ThunderboltOutlined />} loading={process.isPending} disabled={busy} onClick={() => process.mutate()}>
            Проанализировать очередь{status.data?.pending ? ` (${status.data.pending})` : ''}</Button>}
          {can('admin') && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing('new')}>Добавить источник</Button>}
        </>} />
      {busy && <Alert type="info" showIcon style={{ marginBottom: 14 }} title="Идёт сбор или анализ данных" description="Новые сообщения появятся в ленте и на дашбордах по завершении." />}

      <Tabs activeKey={tab} onChange={(k) => setSp((p) => { const n = new URLSearchParams(p); n.set('tab', k); return n })}
        items={TABS.map((t) => ({ key: t.key, label: <span>{t.label} <span className="muted">{count(t)}</span></span> }))} />

      {(tab === 'instagram' || tab === 'threads') && <ConnectionPanel platform={tab} />}

      <div className="filterbar">
        <Input prefix={<SearchOutlined />} allowClear placeholder="Поиск по названию, ссылке, описанию" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 300 }} aria-label="Поиск источников" />
        <Select allowClear placeholder="Состояние" value={statusF} onChange={setStatusF} style={{ width: 230 }} aria-label="Состояние"
          options={Object.entries(CONN).map(([value, v]) => ({ value, label: v.text }))} />
      </div>

      <div className="panel" style={{ padding: 0 }}>
        <Table<Source> rowKey="id" loading={sources.isLoading} dataSource={rows} pagination={false} size="middle" scroll={{ x: 1180 }}
          locale={{ emptyText: <Empty title="Источников нет">Добавьте источник вручную или из списка рекомендованных ниже.</Empty> }}
          columns={[
            { title: 'Источник', render: (_, r) => (
              <div style={{ maxWidth: 420 }}>
                <b>{r.name}</b>{r.is_synthetic && <Tag style={{ marginLeft: 6 }}>синтетические данные</Tag>}
                {r.recommended_key && <Tag color="blue" style={{ marginLeft: 6 }}>из рекомендованных</Tag>}
                {r.url && <div><a href={r.url} target="_blank" rel="noreferrer" style={{ fontSize: 12.5 }}><LinkOutlined /> {r.url.replace('https://', '')}</a></div>}
                {r.description && <div className="muted msg-clamp" style={{ fontSize: 12.5 }}>{r.description}</div>}
                {configSummary(r) && <div className="muted" style={{ fontSize: 12.5 }}>{configSummary(r)}</div>}
              </div>) },
            { title: 'Платформа', width: 120, render: (_, r) => <PlatformTag value={r.platform} /> },
            { title: 'Географический охват', width: 160, dataIndex: 'geo_scope', render: (v) => <span style={{ fontSize: 13 }}>{SCOPE_LABEL[v] ?? v}</span> },
            { title: 'Состояние', width: 220, render: (_, r) => (
              <div>
                <Badge status={CONN[r.connection]?.status ?? 'default'} text={CONN[r.connection]?.text ?? r.connection} />
                {r.last_error && <Tooltip title={r.last_error}><div className="msg-clamp" style={{ fontSize: 12.5, color: r.last_status === 'error' ? '#B8432F' : '#8a6d14' }}>{r.last_error}</div></Tooltip>}
              </div>) },
            { title: 'Последний успешный сбор', width: 150, dataIndex: 'last_success_at', render: fmtDate },
            { title: <Tooltip title="Сообщений о Павлодаре / всего собрано">Сообщений</Tooltip>, width: 110, align: 'right', render: (_, r) => <span><b>{r.local_items}</b><span className="muted"> / {r.items}</span></span> },
            { title: '', width: 250, fixed: 'right', render: (_, r) => (
              <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
                {can('admin') && <Tooltip title={r.enabled ? 'Отключить мониторинг' : 'Включить мониторинг'}><Switch size="small" checked={r.enabled} onChange={() => toggle.mutate(r)} aria-label="Мониторинг" /></Tooltip>}
                {can('operator') && r.auto && <Button size="small" icon={<CloudDownloadOutlined />} disabled={!r.enabled || busy} onClick={() => run.mutate(r.id)}>Собрать</Button>}
                <Tooltip title="История сбора"><Button size="small" icon={<HistoryOutlined />} onClick={() => setHistory(r)} aria-label="История сбора" /></Tooltip>
                {can('admin') && <Tooltip title="Настроить"><Button size="small" icon={<EditOutlined />} onClick={() => setEditing(r)} aria-label="Настроить" /></Tooltip>}
                {can('admin') && (
                  <Popconfirm title="Удалить источник?" description={`Будут удалены и ${r.items} собранных сообщений.`} okText="Удалить"
                    okButtonProps={{ danger: true }} cancelText="Отмена" onConfirm={() => remove.mutate(r)}>
                    <Button size="small" danger icon={<DeleteOutlined />} aria-label="Удалить" />
                  </Popconfirm>
                )}
              </div>) },
          ]} />
      </div>

      {recRows.length > 0 && (
        <Panel title="Рекомендованные источники о Павлодаре" style={{ marginTop: 16 }}
          note="Каждый источник проверен вручную 30.10.2026: указано, что именно подтверждено и как его можно собирать">
          <Table<Recommended> rowKey="key" dataSource={recRows} pagination={false} size="small" scroll={{ x: 1000 }}
            expandable={{ expandedRowRender: (r) => (
              <div style={{ fontSize: 13, lineHeight: 1.6 }}>
                <div><b>Почему полезен:</b> {r.relevance}</div>
                <div><b>Что проверено:</b> {r.verified}</div>
                <div><b>Доступ:</b> {r.access}</div>
              </div>) }}
            columns={[
              { title: 'Источник', render: (_, r) => (
                <div style={{ maxWidth: 380 }}><b>{r.name}</b>
                  <div><a href={r.url} target="_blank" rel="noreferrer" style={{ fontSize: 12.5 }}>{r.url.replace('https://', '')}</a></div>
                  <div className="muted" style={{ fontSize: 12.5 }}>{r.description}</div></div>) },
              { title: 'Платформа', width: 110, render: (_, r) => <PlatformTag value={r.platform} /> },
              { title: 'Содержание', width: 220, dataIndex: 'content', render: (v) => <span style={{ fontSize: 13 }}>{v}</span> },
              { title: 'Охват', width: 140, dataIndex: 'geo_scope', render: (v) => <span style={{ fontSize: 13 }}>{SCOPE_LABEL[v]}</span> },
              { title: 'Сбор', width: 170, dataIndex: 'collection', render: (v) => <Tag color={REC_STATUS[v]?.color}>{REC_STATUS[v]?.text ?? v}</Tag> },
              { title: '', width: 130, render: (_, r) => r.added_source_id
                ? <span className="muted"><CheckCircleOutlined /> Добавлен</span>
                : can('admin') ? <Button size="small" type="primary" icon={<PlusOutlined />} loading={addRec.isPending && addRec.variables === r.key} onClick={() => addRec.mutate(r.key)}>Добавить</Button>
                : null },
            ]} />
        </Panel>
      )}

      <div className="grid g-2" style={{ marginTop: 16, gridTemplateColumns: 'minmax(0,1fr) minmax(0,2fr)', alignItems: 'start' }}>
        <Panel title="Загрузка CSV / XLSX" note="колонки: текст (обязательно), дата, ссылка, автор, реакции">
          {can('operator') ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, fontSize: 13.5 }}>
                Данные о: <Select size="small" value={scope} onChange={setScope} style={{ width: 210 }} aria-label="Охват файла"
                  options={Object.entries(SCOPE_LABEL).map(([value, label]) => ({ value, label }))} />
              </div>
              <Upload.Dragger accept=".csv,.xlsx,.tsv" multiple={false} showUploadList={false} beforeUpload={upload}>
                <p style={{ fontSize: 30, color: '#1F7FC1', margin: 0 }}><InboxOutlined /></p>
                <p style={{ margin: '6px 0 2px', fontWeight: 700 }}>Перетащите файл или нажмите, чтобы выбрать</p>
                <p className="muted" style={{ margin: 0, fontSize: 13 }}>До 20 МБ. Повторная загрузка не создаёт дубликатов.</p>
              </Upload.Dragger>
            </>
          ) : <div className="muted">Загрузка доступна оператору и администратору.</div>}
        </Panel>
        <Panel title="Журнал сбора" note="последние запуски всех источников">
          <RunsTable runs={runs.data} loading={runs.isLoading} />
        </Panel>
      </div>

      {editing && <SourceModal source={editing === 'new' ? null : editing} collectors={collectors.data ?? []} defaultTab={tab}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); invalidate() }} />}
      <Drawer open={!!history} onClose={() => setHistory(null)} size={760} title={history ? `История сбора: ${history.name}` : ''}>
        {history && <RunsTable runs={(runs.data ?? []).filter((r) => r.source_id === history.id)} loading={false} showSource={false} />}
      </Drawer>
    </>
  )
}

function RunsTable({ runs, loading, showSource = true }: { runs?: Run[]; loading: boolean; showSource?: boolean }) {
  return (
    <Table<Run> rowKey="id" size="small" loading={loading} dataSource={runs} pagination={{ pageSize: 8, showSizeChanger: false }} scroll={{ x: 680 }}
      locale={{ emptyText: <Empty title="Запусков ещё не было" /> }}
      expandable={{ rowExpandable: (r) => !!r.error, expandedRowRender: (r) => <Typography.Text style={{ fontSize: 12.5, whiteSpace: 'pre-wrap' }}>{r.error}</Typography.Text> }}
      columns={[
        { title: 'Время', dataIndex: 'started_at', width: 130, render: fmtDate },
        ...(showSource ? [{ title: 'Источник', dataIndex: 'source', render: (v: string, r: Run) => <>{v}<div className="muted" style={{ fontSize: 12 }}>{TRIGGER[r.trigger] ?? r.trigger}</div></> }] : []),
        { title: 'Статус', dataIndex: 'status', width: 100, render: (v, r) => v === 'ok' ? <Tag color={r.error ? 'gold' : 'green'}>{r.error ? 'частично' : 'успешно'}</Tag> : v === 'error' ? <Tag color="red">ошибка</Tag> : <Tag>идёт</Tag> },
        { title: 'Получено', dataIndex: 'fetched', width: 80, align: 'right' },
        { title: 'Новых', dataIndex: 'new_items', width: 70, align: 'right' },
        { title: 'Дубл.', dataIndex: 'duplicates', width: 60, align: 'right' },
        { title: 'Спам', dataIndex: 'spam', width: 60, align: 'right' },
        { title: <Tooltip title="Однозначно о другом населённом пункте — не отправлялись в анализ">Не Павлодар</Tooltip>, dataIndex: 'not_local', width: 100, align: 'right' },
      ]} />
  )
}

function ConnectionPanel({ platform }: { platform: 'instagram' | 'threads' }) {
  const { can } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['connect'], queryFn: () => api.get<Connection[]>('/api/connect/status') })
  const c = data?.find((x) => x.platform === platform)
  const name = platform === 'instagram' ? 'Instagram' : 'Threads'
  const env = platform.toUpperCase()
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); message.success(ok); qc.invalidateQueries({ queryKey: ['connect'] }) } catch (e) { message.error((e as Error).message) }
  }
  if (!c) return null
  return (
    <Panel title={`Подключение ${name}`} style={{ marginBottom: 16 }}
      note={platform === 'instagram' ? 'Официальный Instagram Platform API (Meta). Неофициальные способы не используются.' : 'Официальный Threads API (Meta).'}
      extra={can('admin') && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {!c.connected || c.origin === 'env' ? (
          <Button type="primary" icon={<ApiOutlined />} disabled={!c.app_configured}
            onClick={() => act(async () => { window.location.href = (await api.get<{ url: string }>(`/api/connect/${platform}/start`)).url }, 'Переход к Meta…')}>
            Подключить {name}</Button>
        ) : (
          <>
            <Button icon={<CheckCircleOutlined />} onClick={() => act(() => api.post(`/api/connect/${platform}/test`), 'Подключение работает')}>Проверить</Button>
            <Button icon={<ReloadOutlined />} onClick={() => act(() => api.post(`/api/connect/${platform}/refresh`), 'Токен обновлён')}>Обновить токен</Button>
            <Popconfirm title={`Отключить ${name}?`} okText="Отключить" cancelText="Отмена" onConfirm={() => act(() => api.del(`/api/connect/${platform}`), 'Отключено')}>
              <Button danger icon={<DisconnectOutlined />}>Отключить</Button>
            </Popconfirm>
          </>
        )}
      </div>}>
      <div style={{ marginBottom: 10 }}>
        {c.connected
          ? <Badge status={c.expires_soon ? 'warning' : 'success'} text={<>Подключён{c.username ? ` как @${c.username}` : ''}{c.origin === 'env' ? ' (токен из .env)' : ''}{c.expires_at ? ` · токен действует до ${fmtDate(c.expires_at)}` : ''}</>} />
          : <Badge status="default" text="Не подключён" />}
      </div>
      {!c.app_configured && !c.connected && (
        <Alert type="warning" showIcon style={{ marginBottom: 10 }} title={`Не заданы ${env}_APP_ID и ${env}_APP_SECRET`}
          description={<>Создайте приложение на developers.facebook.com, добавьте продукт «{name} API», укажите redirect URI <code>{c.redirect_uri}</code>, впишите ключи в .env и перезапустите приложение. Либо задайте готовый долгоживущий токен в {env}_ACCESS_TOKEN.</>} />
      )}
      <Table size="small" pagination={false} rowKey="name" dataSource={c.capabilities}
        columns={[{ title: 'Возможность', dataIndex: 'name' }, { title: 'Статус', dataIndex: 'status', width: 170, render: (v) => <Tag color={CAP[v]?.color}>{CAP[v]?.text ?? v}</Tag> },
          { title: 'Что нужно', dataIndex: 'needs', render: (v) => <span className="muted" style={{ fontSize: 12.5 }}>{v}</span> }]} />
    </Panel>
  )
}

function configSummary(s: Source): string {
  const c = s.config ?? {}
  const parts: string[] = []
  const list = (k: string) => (Array.isArray(c[k]) && (c[k] as string[]).length ? (c[k] as string[]).join(', ') : '')
  if (list('channels')) parts.push(`каналы: ${list('channels')}`)
  if (list('chats')) parts.push(`чаты: ${list('chats')}`)
  if (list('feeds')) parts.push(`RSS: ${list('feeds')}`)
  if (list('keywords')) parts.push(`ключевые слова: ${list('keywords')}`)
  if (list('business_accounts')) parts.push(`аккаунты: ${list('business_accounts')}`)
  if (list('hashtags')) parts.push(`хэштеги: ${list('hashtags')}`)
  if (s.type === 'instagram' && c.own_media) parts.push('комментарии своих постов')
  if (!parts.length && ['telegram_web', 'telethon', 'news'].includes(s.type)) return 'Не настроен: укажите каналы или ленты'
  return parts.join(' · ')
}

function SourceModal({ source, collectors, defaultTab, onClose, onSaved }: { source: Source | null; collectors: Collector[]; defaultTab: string; onClose: () => void; onSaved: () => void }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const firstType = collectors.find((c) => c.platform === defaultTab && c.type !== 'upload')?.type ?? 'telegram_web'
  const [type, setType] = useState(source?.type ?? firstType)
  const col = collectors.find((c) => c.type === type)
  const initial: Record<string, unknown> = {
    name: source?.name ?? col?.title, schedule_minutes: source?.schedule_minutes ?? 60, type,
    url: source?.url, description: source?.description, geo_scope: source?.geo_scope ?? (PLATFORM_FOR_TYPE[type] === 'threads' ? 'national' : 'city'),
  }
  col?.fields.forEach((f) => {
    const v = source?.config?.[f.key] ?? f.default
    initial[`cfg_${f.key}`] = f.type === 'list' ? (Array.isArray(v) ? v.join(', ') : v ?? '') : v
  })
  const save = async () => {
    const v = await form.validateFields()
    const config: Record<string, unknown> = {}
    col?.fields.forEach((f) => {
      const x = v[`cfg_${f.key}`]
      config[f.key] = f.type === 'list' ? String(x ?? '').split(/[,\n]/).map((s) => s.trim()).filter(Boolean) : x
    })
    const body = { name: v.name, config, schedule_minutes: v.schedule_minutes, url: v.url || null, description: v.description || null, geo_scope: v.geo_scope }
    try {
      if (source) await api.patch(`/api/sources/${source.id}`, body)
      else await api.post('/api/sources', { type, ...body })
      message.success('Источник сохранён')
      onSaved()
    } catch (e) { message.error((e as Error).message) }
  }
  return (
    <Modal open title={source ? 'Настройка источника' : 'Новый источник'} okText="Сохранить" cancelText="Отмена" onOk={save} onCancel={onClose} width={620} destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={initial} key={type} requiredMark={false}>
        {!source && (
          <Form.Item label="Тип источника" name="type">
            <Select onChange={setType} options={collectors.filter((c) => !['upload', 'demo'].includes(c.type)).map((c) => ({ value: c.type, label: c.title }))} />
          </Form.Item>
        )}
        {col && <Alert type="info" title={col.description} style={{ marginBottom: 14 }} />}
        <Form.Item label="Название" name="name" rules={[{ required: true, min: 2, message: 'Укажите название' }]}><Input /></Form.Item>
        <Form.Item label="Ссылка на источник" name="url" rules={[{ type: 'url', message: 'Нужна ссылка вида https://…' }]}><Input placeholder="https://t.me/…" /></Form.Item>
        <Form.Item label="Описание" name="description"><Input.TextArea autoSize={{ minRows: 2 }} maxLength={2000} /></Form.Item>
        <Form.Item label="Географический охват источника" name="geo_scope"
          extra="Подсказка для геофильтра: в источнике о самом городе сообщения без указания места считаются павлодарскими; в областных и общих — требуют признаков города.">
          <Select options={Object.entries(SCOPE_LABEL).map(([value, label]) => ({ value, label }))} />
        </Form.Item>
        {col?.fields.map((f) => (
          <Form.Item key={f.key} label={f.label} name={`cfg_${f.key}`} valuePropName={f.type === 'bool' ? 'checked' : 'value'}
            rules={f.required ? [{ required: true, message: 'Обязательное поле' }] : []}>
            {f.type === 'bool' ? <Switch /> : f.type === 'int' ? <InputNumber min={1} max={1000} /> : f.type === 'list' ? <Input.TextArea autoSize placeholder="через запятую" /> : <Input />}
          </Form.Item>
        ))}
        <Form.Item label="Интервал сбора, минут" name="schedule_minutes"><InputNumber min={5} max={1440} /></Form.Item>
      </Form>
    </Modal>
  )
}
