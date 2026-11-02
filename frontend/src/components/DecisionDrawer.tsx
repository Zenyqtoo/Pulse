import { ArrowRightOutlined, CheckCircleOutlined, LockOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Drawer, Input, Skeleton } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../context'
import { STATUS_LABEL } from '../theme'

interface Evidence { id: number; text: string; source: string; url: string | null; published_at: string; is_direct: boolean; synthetic: boolean; voice: 'resident' | 'media' }
interface Decision {
  cluster_id: number; title: string; department_name: string; district: string | null; generated_at: string
  available: boolean; synthetic: boolean; period_start: string; period_end: string; status: string
  selection_note?: string
  metrics: {
    messages: number; known_accounts: number; messages_without_author: number; sources: number
    current_24h: number; previous_24h: number; growth_pct: number | null; growth_abs: number; small_base: boolean
    synthetic_messages: number; direct_messages: number; hidden_direct: number; resident_messages: number; media_posts: number
  }
  topics: { label: string; count: number; share: number; item_ids: number[] }[]
  objects: { label: string; count: number }[]
  peaks: { hour: number; count: number }[]; daily: { date: string; count: number }[]
  demands: { text: string; item_id: number; is_direct: boolean }[]; affected: string[]
  related_departments: string[]; checks: string[]; method: string
  voices: Evidence[]; evidence: Evidence[]
}

const date = (v: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Almaty' }).format(new Date(v))
const day = (v: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(v))
const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10, m100 = n % 100
  return `${n} ${m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many}`
}

// The next step the operator can take from each status; the person decides, the system only records it.
const NEXT: Record<string, { status: string; label: string; done: string } | undefined> = {
  new: { status: 'transferred', label: 'Передать в подразделение', done: 'Проблема передана ответственному подразделению' },
  transferred: { status: 'in_progress', label: 'Взять в работу', done: 'Проблема отмечена как «В работе»' },
  in_progress: { status: 'resolved', label: 'Отметить решённой', done: 'Проблема отмечена как решённая' },
}

function growthText(m: Decision['metrics']) {
  if (m.previous_24h === 0) return m.current_24h ? 'В предыдущие сутки сообщений не было, поэтому рост в процентах не считается.' : 'За последние двое суток новых сообщений нет.'
  const diff = m.growth_abs === 0 ? 'Столько же, сколько в предыдущие сутки.' : `На ${plural(Math.abs(m.growth_abs), 'сообщение', 'сообщения', 'сообщений')} ${m.growth_abs > 0 ? 'больше' : 'меньше'}, чем в предыдущие сутки.`
  if (m.small_base) return `${diff} Процент не приводим: база меньше 10 сообщений, он был бы неустойчивым.`
  return `${diff} Изменение: ${m.growth_pct! > 0 ? '+' : ''}${m.growth_pct}%.`
}

// Daily counts with empty days filled in, so a gap is visible as a gap.
function fillDays(daily: Decision['daily'], last = 14) {
  if (!daily.length) return []
  const counts = new Map(daily.map((d) => [d.date, d.count]))
  const end = new Date(daily[daily.length - 1].date + 'T00:00:00Z')
  const start = new Date(Math.max(new Date(daily[0].date + 'T00:00:00Z').getTime(), end.getTime() - (last - 1) * 864e5))
  const out: { date: string; count: number }[] = []
  for (let t = start.getTime(); t <= end.getTime(); t += 864e5) {
    const k = new Date(t).toISOString().slice(0, 10)
    out.push({ date: k, count: counts.get(k) ?? 0 })
  }
  return out
}

function Section({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return <section className="brief-section"><div className="brief-section-title"><span>{n}</span><h2>{title}</h2></div>{children}</section>
}

export default function DecisionDrawer() {
  const [sp, setSp] = useSearchParams()
  const id = sp.get('decision')
  const { can } = useApp()
  const qc = useQueryClient()
  const { message } = App.useApp()
  const [comment, setComment] = useState('')
  useEffect(() => setComment(''), [id])
  const { data: d, isLoading, error } = useQuery({ queryKey: ['decision', id], queryFn: () => api.get<Decision>(`/api/clusters/${id}/decision`), enabled: !!id, staleTime: 0 })
  const close = () => setSp((p) => { const n = new URLSearchParams(p); n.delete('decision'); return n })
  const evidence = (itemId: number) => setSp((p) => { const n = new URLSearchParams(p); n.set('item', String(itemId)); return n })
  const next = d ? NEXT[d.status] : undefined
  const route = useMutation({
    mutationFn: () => api.patch(`/api/clusters/${id}`, { status: next!.status, comment: comment.trim() || undefined }),
    onSuccess: () => {
      ['clusters', 'overview', 'decision', 'ops', 'problem'].forEach((key) => qc.invalidateQueries({ queryKey: [key] }))
      message.success(`${next!.done}. Запись добавлена в журнал.`)
      setComment('')
    },
    onError: (e: Error) => message.error(e.message),
  })

  const m = d?.metrics
  const days = d ? fillDays(d.daily) : []
  const dayMax = Math.max(1, ...days.map((x) => x.count))
  const hourMax = Math.max(1, ...(d?.peaks ?? []).map((p) => p.count))
  const place = d && `${d.district || 'Район не определён'}${d.objects.length ? ` · упоминается: ${d.objects[0].label}` : ''}`

  return (
    <Drawer open={!!id} onClose={close} size={860} className="decision-drawer" title="Данные для решения" destroyOnHidden>
      {isLoading && <Skeleton active paragraph={{ rows: 12 }} />}
      {error && <Alert type="error" showIcon title="Не удалось подготовить данные" description={(error as Error).message} />}
      {d && m && (
        <div className="decision-document">
          <div className="decision-document-top">
            <span className="eyebrow">CITY ALERT · ПРОБЛЕМА №{d.cluster_id}</span>
            <span className={`document-stamp status-${d.status}`}>{STATUS_LABEL[d.status] ?? d.status}</span>
          </div>
          <h1>{d.title}</h1>
          {d.selection_note && <Alert type="info" showIcon title="Подборка для демонстрации" description={d.selection_note} style={{ marginBottom: 16 }} />}
          <p className="document-location">{place} · {d.department_name}</p>
          {d.synthetic && (
            <div className="demo-ribbon">УЧЕБНЫЙ СЦЕНАРИЙ · {m.synthetic_messages === m.messages ? 'все сообщения синтетические' : `${m.synthetic_messages} из ${m.messages} сообщений синтетические`}</div>
          )}
          {m.hidden_direct > 0 && (
            <p className="document-note hidden-note"><LockOutlined /> Не показаны и не учтены в цифрах: {plural(m.hidden_direct, 'личное обращение', 'личных обращения', 'личных обращений')}. Они доступны только оператору.</p>
          )}

          {!d.available ? <Alert type="info" showIcon title="В этой проблеме нет сообщений, доступных вашей роли." /> : <>
            <div className="brief-label">Что происходит</div>
            <p className="brief-lead">
              С {date(d.period_start)} по {date(d.period_end)} — <b>{plural(m.messages, 'сообщение', 'сообщения', 'сообщений')}</b>
              {m.media_posts > 0 ? <>: от жителей — <b>{m.resident_messages}</b>, публикаций СМИ и официальных каналов — <b>{m.media_posts}</b>.</> : ' от жителей.'}{' '}
              За последние сутки — <b>{m.current_24h}</b>, за предыдущие — <b>{m.previous_24h}</b>. {growthText(m)}
            </p>

            <div className="brief-metrics">
              <div><strong>{m.messages}</strong><span>сообщений без дубликатов</span></div>
              <div><strong>{m.known_accounts}</strong><span>разных аккаунтов авторов</span></div>
              <div><strong>{m.sources}</strong><span>{m.sources === 1 ? 'источник' : 'источников'}</span></div>
            </div>
            <p className="document-note">
              Аккаунты не равны людям: один человек может писать с разных аккаунтов и платформ.
              {m.messages_without_author > 0 && ` У ${plural(m.messages_without_author, 'сообщения', 'сообщений', 'сообщений')} автор неизвестен.`}
            </p>

            <section className="resident-voices">
              <div className="eyebrow">ГОЛОСОМ ЖИТЕЛЕЙ</div>
              {d.voices.length ? <p className="document-note">Показаны примеры: {d.voices.length} из {m.resident_messages} сообщений пользователей. Это формулировки авторов, а не оценка мнения всех жителей.</p>
                : <p className="document-note">Сообщений самих жителей в этой проблеме нет — только публикации СМИ и официальных каналов. Их не выдаём за голос жителей.</p>}
              {d.voices.map((q) => (
                <blockquote key={q.id}>«{q.text}»
                  <button onClick={() => evidence(q.id)}>{q.is_direct && <><LockOutlined /> Личное · </>}Обращение №{q.id} · {q.source} · {date(q.published_at)} ↗</button>
                </blockquote>
              ))}
            </section>

            <Section n="01" title="Как менялось">
              {days.length > 1 ? (
                <div className="day-chart" role="img" aria-label="Число обращений по дням">
                  {days.map((x) => (
                    <div key={x.date} title={`${day(x.date)} — ${plural(x.count, 'обращение', 'обращения', 'обращений')}`}>
                      <b>{x.count || ''}</b><i style={{ height: `${Math.max(2, (x.count / dayMax) * 64)}px`, opacity: x.count ? 1 : .2 }} /><span>{day(x.date).replace('.', '')}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="document-note">Все сообщения за один день — динамику по дням показать нельзя.</p>}
              <p className="document-note">Дни по времени Павлодара (UTC+5), по дате публикации. Полные графики — в разделе «Аналитика».</p>
            </Section>

            <Section n="02" title={m.resident_messages === 0 ? 'О чём пишут СМИ и каналы' : m.media_posts ? 'О чём сообщения' : 'Что сообщают жители'}>
              {d.topics.map((t) => (
                <div className="brief-topic" key={t.label}>
                  <div><b>{t.label}</b><span>{t.count} из {m.messages}</span></div>
                  <div className="brief-topic-track"><i style={{ width: `${t.share}%` }} /></div>
                  <button onClick={() => evidence(t.item_ids[0])}>Проверить по сообщению №{t.item_ids[0]} <ArrowRightOutlined /></button>
                </div>
              ))}
              {d.objects.length > 0 && <p>Упоминаемые объекты: <b>{d.objects.map((o) => `${o.label} (${o.count})`).join(', ')}</b>.</p>}
              {d.affected.length > 0 && <p>В текстах упоминаются: <b>{d.affected.join(', ')}</b>. Это слова в сообщениях, а не число затронутых жителей.</p>}
              <p className="document-note">Темы и объекты определены автоматической классификацией и могут требовать проверки.</p>
            </Section>

            <Section n="03" title="О чём просят">
              {d.demands.length ? d.demands.map((q, i) => (
                <blockquote key={`${q.item_id}-${i}`}>«{q.text}»<button onClick={() => evidence(q.item_id)}>{q.is_direct && <><LockOutlined /> Личное · </>}Обращение №{q.item_id} ↗</button></blockquote>
              )) : <p className="document-note">Явных просьб в сообщениях жителей не найдено. Публикации СМИ сюда не входят, а требования за жителей система не додумывает.</p>}
            </Section>

            <Section n="04" title="Когда публикуют">
              <div className="hour-chart" role="img" aria-label="Часы публикации сообщений по времени Павлодара">
                {Array.from({ length: 24 }, (_, h) => {
                  const n = d.peaks.find((p) => p.hour === h)?.count ?? 0
                  return <div key={h} title={`${String(h).padStart(2, '0')}:00 — ${n}`}><i style={{ height: `${Math.max(2, (n / hourMax) * 56)}px`, opacity: n ? 1 : .15 }} /><span>{h % 4 === 0 ? String(h).padStart(2, '0') : ''}</span></div>
                })}
              </div>
              <p className="document-note">Время публикации по Павлодару (UTC+5). Когда произошло само событие, из этого не следует.</p>
            </Section>

            <section className="decision-checks">
              <div className="eyebrow">ПЕРЕД РЕШЕНИЕМ</div>
              <h2>Чего мы пока не знаем</h2>
              <p>Пробелы в данных, которые стоит закрыть или учесть.</p>
              {d.checks.map((q, i) => <div key={q}><span>{String(i + 1).padStart(2, '0')}</span>{q}</div>)}
            </section>

            <Section n="05" title="Доказательства и первоисточники">
              <p className="document-note">Разные источники могут перепечатывать друг друга, поэтому их число само по себе не подтверждает факт.</p>
              <details className="evidence-details">
                <summary>Все {plural(d.evidence.length, 'сообщение', 'сообщения', 'сообщений')}</summary>
                {d.evidence.map((i) => (
                  <article className="evidence-item" key={i.id}>
                    <div><b>№{i.id} · {i.source}</b><span>{date(i.published_at)}{i.voice === 'media' ? ' · публикация СМИ / канала' : ''}{i.is_direct ? ' · личное обращение' : ''}{i.synthetic ? ' · учебное' : ''}</span></div>
                    <p>{i.text}</p>
                    <button onClick={() => evidence(i.id)}>Открыть обращение ↗</button>
                    {i.url && <a href={i.url} target="_blank" rel="noreferrer">Первоисточник ↗</a>}
                  </article>
                ))}
              </details>
              <Link className="text-action" to={`/feed?cluster_id=${d.cluster_id}&days=365`}>Открыть все сообщения проблемы в ленте <ArrowRightOutlined /></Link>
            </Section>
          </>}

          <div className="brief-handoff">
            <CheckCircleOutlined />
            <div className="handoff-text">
              <b>Решение принимает сотрудник</b>
              <p>Ответственное подразделение: {d.department_name}.{d.related_departments.length > 0 && ` В классификации также упоминаются: ${d.related_departments.join(', ')}.`} Статус: {STATUS_LABEL[d.status] ?? d.status}.</p>
            </div>
            {can('operator') && d.available && next && !d.selection_note && (
              <div className="handoff-form">
                <Input.TextArea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} autoSize={{ minRows: 2, maxRows: 4 }}
                  placeholder="Основание решения: что проверено, какие ресурсы учтены (попадёт в журнал)" aria-label="Основание решения" />
                <Button type="primary" loading={route.isPending} onClick={() => route.mutate()}>{next.label}</Button>
              </div>
            )}
            {!can('operator') && <p className="handoff-role">Менять статус может оператор или администратор.</p>}
          </div>
          <p className="document-method">{d.method} Подготовлено {date(d.generated_at)}.</p>
        </div>
      )}
    </Drawer>
  )
}
