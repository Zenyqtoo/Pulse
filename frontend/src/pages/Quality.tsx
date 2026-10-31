import { DownloadOutlined, PlayCircleOutlined, UploadOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Radio, Segmented, Select, Skeleton, Table, Tabs, Tag, Upload } from 'antd'
import { useState } from 'react'
import { api, download } from '../api'
import Chart from '../components/Chart'
import { Empty, fmtDate, MaskedText, PageHead, Panel } from '../components/ui'
import { useApp } from '../context'
import { C, LANG_LABEL, SENT_LABEL } from '../theme'

interface EvalRun {
  id: number; created_at: string; split: string; origin: string; mode: string; model: string; n: number
  dept_accuracy: number | null; dept_accuracy_lenient: number | null; sentiment_accuracy: number | null
  dept_macro_f1: number | null; sentiment_macro_f1: number | null
  details: { department?: Metrics; sentiment?: Metrics; by_lang?: Record<string, { n: number; dept_accuracy: number; sentiment_accuracy: number }> }
}
interface Metrics { accuracy: number; macro_f1: number; labels: string[]; confusion: number[][]; per_class: Record<string, { precision: number; recall: number; f1: number; support: number }> }
interface Summary {
  llm_enabled: boolean; llm_model: string; summary_model: string; prompt_version: string; embedding_backend: string; review_threshold: number
  gold_counts: Record<string, number>; models: Record<string, number>; analysed: number; review_share: number; corrected_departments: number
  latency_ms: { p50: number | null; p95: number | null; n: number }; runs: EvalRun[]
}

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`)
const ORIGIN: Record<string, string> = { real: 'реальные данные', synthetic: 'демо-набор (синтетический)', all: 'все данные' }
const SPLIT: Record<string, string> = { test: 'тестовая выборка', dev: 'выборка для настройки', all: 'вся разметка' }

export default function Quality() {
  return (
    <>
      <PageHead title="Качество ИИ" sub="Измеренная точность на размеченных вручную обращениях. Цели из ТЗ: тональность ≥ 80%, подразделение ≥ 75%." />
      <Tabs items={[{ key: 'r', label: 'Результаты', children: <Results /> }, { key: 'l', label: 'Разметка', children: <Labeling /> }]} />
    </>
  )
}

function Results() {
  const { can, deptName } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [split, setSplit] = useState('test')
  const [origin, setOrigin] = useState('real')
  const [mode, setMode] = useState('stored')
  const { data, isLoading } = useQuery({ queryKey: ['quality'], queryFn: () => api.get<Summary>('/api/quality') })
  const run = useMutation({
    mutationFn: () => api.post<EvalRun>('/api/quality/evaluate', { split, origin, mode }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['quality'] }); message.success('Оценка выполнена') },
    onError: (e: Error) => message.error(e.message),
  })
  if (isLoading || !data) return <Skeleton active paragraph={{ rows: 10 }} />
  const last = data.runs[0]
  const g = data.gold_counts
  const realGold = (g.real_test ?? 0) + (g.real_dev ?? 0)
  const lat = data.latency_ms

  return (
    <>
      {!data.llm_enabled && (
        <Alert type="warning" showIcon style={{ marginBottom: 14 }} title="Сейчас работает резервный анализ по правилам"
          description="Ключ Claude API не задан, поэтому подразделение и тональность определяются словарями. Для заявленного качества задайте ANTHROPIC_API_KEY и переанализируйте обращения." />
      )}
      <div className="kpis" style={{ marginTop: 0 }}>
        <Tile label="Модель анализа" value={data.llm_enabled ? data.llm_model : 'правила'} note={`промпт ${data.prompt_version}`} small />
        <Tile label="Векторы для кластеров" value={data.embedding_backend.replace('st:', '')} note="поиск похожих обращений" small />
        <Tile label="Время анализа (LLM)" value={lat.p50 ? `${(lat.p50 / 1000).toFixed(1)} с` : '—'} note={lat.p95 ? `95% быстрее ${(lat.p95 / 1000).toFixed(1)} с · цель ≤ 5 с` : 'нет вызовов LLM'} />
        <Tile label="На ручной проверке" value={`${data.review_share}%`} note={`уверенность < ${data.review_threshold}`} />
        <Tile label="Размечено вручную" value={String(realGold)} note={`реальных; тест ${g.real_test ?? 0}, настройка ${g.real_dev ?? 0}; демо ${(g.synthetic_test ?? 0) + (g.synthetic_dev ?? 0)}`} />
      </div>

      {can('operator') && (
        <Panel title="Запустить оценку" note="метрики считаются по исходному ответу модели, а не по исправлениям операторов">
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <Select value={origin} onChange={setOrigin} style={{ width: 240 }} aria-label="Данные"
              options={[{ value: 'real', label: 'Реальные данные' }, { value: 'synthetic', label: 'Демо-набор (синтетический)' }, { value: 'all', label: 'Все' }]} />
            <Select value={split} onChange={setSplit} style={{ width: 220 }} aria-label="Выборка"
              options={[{ value: 'test', label: 'Тестовая (75%)' }, { value: 'dev', label: 'Для настройки (25%)' }, { value: 'all', label: 'Вся разметка' }]} />
            <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)}>
              <Radio.Button value="stored">Сохранённые ответы</Radio.Button>
              <Radio.Button value="rerun">Прогнать заново</Radio.Button>
            </Radio.Group>
            <Button type="primary" icon={<PlayCircleOutlined />} loading={run.isPending} onClick={() => run.mutate()}>Оценить</Button>
          </div>
        </Panel>
      )}

      {!last && <Panel style={{ marginTop: 16 }}><Empty title="Оценок ещё не было">Разметьте 150–200 реальных обращений на вкладке «Разметка», затем запустите оценку.</Empty></Panel>}
      {last && (
        <>
          <div style={{ margin: '18px 0 8px', fontSize: 14 }}>
            Последняя оценка: {fmtDate(last.created_at)} · {ORIGIN[last.origin]} · {SPLIT[last.split]} · {last.n} обращений · модель: {last.model}
          </div>
          {last.origin !== 'real' && (
            <Alert type="warning" showIcon style={{ marginBottom: 12 }} title="Оценка на синтетическом демо-наборе"
              description="Демо-набор составлен командой и использовался при настройке правил, поэтому эти цифры проверяют работу конвейера, а не качество на реальных обращениях." />
          )}
          <div className="grid g-3">
            <Target label="Тональность" value={last.sentiment_accuracy} target={0.8} note={`macro-F1 ${pct(last.sentiment_macro_f1)}`} />
            <Target label="Подразделение (основное)" value={last.dept_accuracy} target={0.75} note={`macro-F1 ${pct(last.dept_macro_f1)}`} />
            <Target label="Подразделение (в списке предложенных)" value={last.dept_accuracy_lenient} target={0.75} note="верное среди 1–3 предложенных" />
          </div>
          {last.details.by_lang && (
            <Panel title="По языкам" style={{ marginTop: 16 }} note="казахские и смешанные тексты отдельно — подтверждение п. 3.1.6">
              <Table size="small" pagination={false} rowKey="lang"
                dataSource={Object.entries(last.details.by_lang).map(([lang, v]) => ({ lang, ...v }))}
                columns={[{ title: 'Язык', dataIndex: 'lang', render: (v) => LANG_LABEL[v] ?? v }, { title: 'Обращений', dataIndex: 'n', align: 'right' },
                  { title: 'Подразделение', dataIndex: 'dept_accuracy', align: 'right', render: pct }, { title: 'Тональность', dataIndex: 'sentiment_accuracy', align: 'right', render: pct }]} />
            </Panel>
          )}
          <div className="grid g-2" style={{ marginTop: 16 }}>
            {last.details.department && <Confusion title="Матрица ошибок: подразделения" m={last.details.department} name={deptName} />}
            {last.details.sentiment && <Confusion title="Матрица ошибок: тональность" m={last.details.sentiment} name={(c) => SENT_LABEL[c] ?? c} />}
          </div>
          <Panel title="История оценок" style={{ marginTop: 16 }}>
            <Table<EvalRun> size="small" rowKey="id" dataSource={data.runs} pagination={false} scroll={{ x: 760 }}
              columns={[{ title: 'Дата', dataIndex: 'created_at', render: fmtDate }, { title: 'Данные', dataIndex: 'origin', render: (v) => ORIGIN[v] },
                { title: 'Выборка', dataIndex: 'split', render: (v) => SPLIT[v] }, { title: 'N', dataIndex: 'n', align: 'right' },
                { title: 'Тональность', dataIndex: 'sentiment_accuracy', align: 'right', render: pct },
                { title: 'Подразделение', dataIndex: 'dept_accuracy', align: 'right', render: pct }, { title: 'Модель', dataIndex: 'model' }]} />
          </Panel>
        </>
      )}
    </>
  )
}

function Tile({ label, value, note, small }: { label: string; value: string; note: string; small?: boolean }) {
  return <div className="kpi"><span className="kpi-label">{label}</span>
    <span className="figure kpi-value" style={small ? { fontSize: 15, lineHeight: 1.5, wordBreak: 'break-all' } : undefined}>{value}</span><span className="kpi-note">{note}</span></div>
}

function Target({ label, value, target, note }: { label: string; value: number | null; target: number; note: string }) {
  const ok = value !== null && value >= target
  return (
    <div className="panel">
      <div className="kpi-label">{label}</div>
      <div className="figure" style={{ fontSize: 40, color: value === null ? C.muted : ok ? C.green : C.brick }}>{pct(value)}</div>
      <div style={{ height: 8, background: '#E9EEF3', borderRadius: 4, position: 'relative', margin: '8px 0' }}>
        <div style={{ width: `${(value ?? 0) * 100}%`, height: '100%', borderRadius: 4, background: ok ? C.green : C.brick }} />
        <div style={{ position: 'absolute', left: `${target * 100}%`, top: -4, height: 16, width: 2, background: C.ink }} title={`цель ${target * 100}%`} />
      </div>
      <div className="muted" style={{ fontSize: 13 }}>Цель ТЗ: {target * 100}% · {ok ? 'достигнута' : 'не достигнута'} · {note}</div>
    </div>
  )
}

function Confusion({ title, m, name }: { title: string; m: Metrics; name: (c: string) => string }) {
  const labels = m.labels.map(name)
  const data: [number, number, number][] = []
  m.confusion.forEach((row, i) => row.forEach((v, j) => data.push([j, i, v])))
  const max = Math.max(1, ...data.map((d) => d[2]))
  return (
    <Panel title={title} note="строки — разметка человека, столбцы — ответ модели">
      <Chart height={Math.max(240, labels.length * 34 + 90)} option={{
        grid: { left: 8, right: 8, top: 8, bottom: 8, containLabel: true },
        tooltip: { formatter: (p: unknown) => { const v = (p as { value: number[] }).value; return `Человек: ${labels[v[1]]}<br/>Модель: ${labels[v[0]]}<br/>${v[2]}` } },
        xAxis: { type: 'category', data: labels, axisLabel: { rotate: 40, fontSize: 11 }, splitArea: { show: true } },
        yAxis: { type: 'category', data: labels, inverse: true, axisLabel: { fontSize: 11 }, splitArea: { show: true } },
        visualMap: { show: false, min: 0, max, inRange: { color: ['#F4F8FB', '#9CC7E6', C.ink] } },
        series: [{ type: 'heatmap', data, label: { show: true, fontSize: 11, formatter: (p: unknown) => { const v = (p as { value: number[] }).value[2]; return v ? String(v) : '' } } }],
      }} />
    </Panel>
  )
}

function Labeling() {
  const { meta, can } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [origin, setOrigin] = useState('real')
  const [choice, setChoice] = useState<Record<number, { department?: string; sentiment?: string }>>({})
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['labeling', origin], enabled: can('operator'),
    queryFn: () => api.get<{ remaining: number; items: { id: number; text: string; lang: string; source: string; is_synthetic: boolean }[] }>('/api/quality/labeling', { origin, limit: 10 }),
  })
  const save = useMutation({
    mutationFn: ({ id, department, sentiment }: { id: number; department: string; sentiment: string }) => api.put(`/api/quality/gold/${id}`, { department, sentiment }),
    onSuccess: (_, v) => { setDone((d) => [...d, v.id]); qc.invalidateQueries({ queryKey: ['quality'] }) },
    onError: (e: Error) => message.error(e.message),
  })
  const [done, setDone] = useState<number[]>([])
  if (!can('operator')) return <Panel><Empty title="Разметка доступна оператору и администратору" /></Panel>
  const importGold = async (file: File) => {
    const fd = new FormData(); fd.append('file', file)
    try { const r = await api.post<{ imported: number }>('/api/quality/gold/import', fd); message.success(`Импортировано меток: ${r.imported}`); qc.invalidateQueries({ queryKey: ['quality'] }) }
    catch (e) { message.error((e as Error).message) }
    return false
  }
  const items = (data?.items ?? []).filter((i) => !done.includes(i.id))
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 14 }} title="Слепая разметка"
        description="Ответ модели здесь не показывается, чтобы не влиять на разметку. Каждое обращение автоматически попадает в тестовую (75%) или настроечную (25%) выборку; тестовые обращения никогда не используются как примеры для модели." />
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <Segmented value={origin} onChange={(v) => { setOrigin(v as string); setDone([]) }}
          options={[{ value: 'real', label: 'Реальные данные' }, { value: 'synthetic', label: 'Демо-набор' }]} />
        <span className="muted">Осталось неразмеченных: {data?.remaining ?? '—'}</span>
        <Button onClick={() => { setDone([]); refetch() }} loading={isFetching}>Следующие 10</Button>
        <Button icon={<DownloadOutlined />} onClick={() => download('/api/quality/gold/export').catch((e) => message.error(e.message))}>Выгрузить разметку</Button>
        <Upload accept=".csv" showUploadList={false} beforeUpload={importGold}><Button icon={<UploadOutlined />}>Загрузить разметку CSV</Button></Upload>
      </div>
      {isLoading && <Skeleton active />}
      {data && items.length === 0 && <Panel><Empty title={data.remaining ? 'Пачка размечена' : 'Все обращения размечены'}>
        {data.remaining ? 'Нажмите «Следующие 10», чтобы продолжить.' : 'Можно запускать оценку на вкладке «Результаты».'}</Empty></Panel>}
      {items.map((it) => {
        const c = choice[it.id] ?? {}
        return (
          <div key={it.id} className="panel" style={{ marginBottom: 10 }}>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 4 }}>№{it.id} · {it.source} · {LANG_LABEL[it.lang] ?? it.lang}{it.is_synthetic && <Tag style={{ marginLeft: 6 }}>демо</Tag>}</div>
            <MaskedText text={it.text} />
            <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
              <Select placeholder="Подразделение" style={{ width: 230 }} value={c.department} aria-label="Подразделение"
                onChange={(v) => setChoice({ ...choice, [it.id]: { ...c, department: v } })} options={meta?.departments.map((d) => ({ value: d.code, label: d.name }))} />
              <Segmented value={c.sentiment ?? ''} onChange={(v) => setChoice({ ...choice, [it.id]: { ...c, sentiment: v as string } })}
                options={[{ value: 'negative', label: 'Отрицательная' }, { value: 'neutral', label: 'Нейтральная' }, { value: 'positive', label: 'Положительная' }]} />
              <Button type="primary" disabled={!c.department || !c.sentiment} loading={save.isPending && save.variables?.id === it.id}
                onClick={() => save.mutate({ id: it.id, department: c.department!, sentiment: c.sentiment! })}>Сохранить метку</Button>
            </div>
          </div>
        )
      })}
    </>
  )
}
