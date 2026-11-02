import { ArrowRightOutlined, ExportOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Skeleton } from 'antd'
import { useSearchParams } from 'react-router-dom'
import type { CSSProperties } from 'react'
import { api } from '../api'

// Defense screen: a few real problems chosen for the demo. Everything shown comes from the API;
// empty fields stay empty, and counts are records and publications, never people.
type DefenseCase = {
  id: number
  title: string
  summary: string
  why_demo: string
  period_note: string
  evidence_note: string
  coverage: { residents: number; media: number; sources: number }
  primary_sources: { label: string; url: string }[]
  updated_at: string
}

const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10, m100 = n % 100
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many
}
const stamp = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Almaty' }).format(d)
}
// Only plain web links are rendered as links.
const safeUrl = (url: string) => /^https?:\/\//i.test(url)

const note: CSSProperties = { display: 'flex', gap: 10, alignItems: 'flex-start', fontSize: 13, lineHeight: 1.5, color: 'var(--text)', margin: '0 0 10px' }
const label: CSSProperties = { display: 'block', fontSize: 11, fontWeight: 700, letterSpacing: 1.2, color: 'var(--muted)', textTransform: 'uppercase', marginBottom: 3 }

function CaseCard({ c, index, onOpen }: { c: DefenseCase; index: number; onOpen: () => void }) {
  const { residents, media, sources } = c.coverage
  const links = c.primary_sources.filter((s) => safeUrl(s.url))
  const updated = stamp(c.updated_at)
  return (
    <article className="lead-case" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="case-top"><span className="eyebrow">СЦЕНАРИЙ {String(index + 1).padStart(2, '0')} · ПРОБЛЕМА №{c.id}</span></div>
      <h2>{c.title}</h2>
      {c.summary && <p style={{ color: 'var(--muted)', fontSize: 14, lineHeight: 1.55, margin: '0 0 4px' }}>{c.summary}</p>}

      <div className="case-numbers">
        <div><strong>{residents}</strong><span>Сообщения пользователей</span></div>
        <div><strong>{media}</strong><span>Публикации СМИ</span></div>
        <div><strong>{sources}</strong><span>{plural(sources, 'Источник', 'Источника', 'Источников')}</span></div>
      </div>

      {residents === 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 14 }}
          title="Сообщений пользователей в этой проблеме нет"
          description="Картина собрана только по публикациям СМИ и каналов. Новость о проблеме не равна жалобе." />
      )}

      {c.why_demo && <p style={note}><span className="signal-dot" /><span><b style={label}>Почему этот пример</b>{c.why_demo}</span></p>}
      {c.period_note && <p style={note}><span className="signal-dot" style={{ background: 'var(--gold)' }} /><span><b style={label}>Период</b>{c.period_note}</span></p>}
      {c.evidence_note && <p style={note}><span className="signal-dot" style={{ background: 'var(--brick)' }} /><span><b style={label}>Доказательства и ограничения</b>{c.evidence_note}</span></p>}
      {sources > 1 && (
        <p style={{ ...note, color: 'var(--muted)', fontSize: 12 }}>
          Несколько источников — не обязательно независимые подтверждения: публикации могут пересказывать друг друга.
        </p>
      )}

      <div style={{ marginTop: 'auto', paddingTop: 12 }}>
        {links.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <span style={label}>Публичные первоисточники</span>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 4 }}>
              {links.map((s) => (
                <li key={s.url} style={{ fontSize: 13, minWidth: 0 }}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ overflowWrap: 'anywhere' }}>
                    {s.label || s.url} <ExportOutlined style={{ fontSize: 11 }} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="case-actions" style={{ flexWrap: 'wrap', gap: 12 }}>
          <Button type="primary" size="large" onClick={onOpen}>Открыть карточку к решению <ArrowRightOutlined /></Button>
          {updated && <span style={{ fontSize: 12, color: 'var(--muted)' }}>Данные обновлены: {updated}</span>}
        </div>
      </div>
    </article>
  )
}

export default function Defense() {
  const [, setSp] = useSearchParams()
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['defense-cases'],
    queryFn: () => api.get<DefenseCase[]>('/api/defense/cases'),
  })
  // The decision card is mounted by the layout and opens from ?decision=ID on any page.
  const open = (id: number) => setSp((p) => { const n = new URLSearchParams(p); n.set('decision', String(id)); return n })
  const cases = data ?? []

  return (
    <div className="desk">
      <div className="desk-heading">
        <div>
          <div className="eyebrow">CITY ALERT · ЗАЩИТА</div>
          <h1>Сценарии для защиты</h1>
          <p>Редакторская подборка реальных записей из базы. Даты и ограничения указаны в каждом примере; первоисточники доступны по ссылкам.</p>
        </div>
      </div>

      {error && (
        <Alert type="error" showIcon title="Не удалось загрузить сценарии" description={(error as Error).message}
          action={<Button size="small" loading={isFetching} onClick={() => refetch()}>Повторить</Button>} />
      )}
      {isLoading && <Skeleton active paragraph={{ rows: 8 }} />}
      {!isLoading && !error && cases.length === 0 && (
        <div className="desk-empty">
          <h2>Сценарии пока не подготовлены</h2>
          <p>Когда в базе появятся подходящие реальные проблемы, они будут показаны здесь.</p>
        </div>
      )}

      {cases.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 360px), 1fr))', gap: 20, alignItems: 'stretch' }}>
          {cases.map((c, i) => <CaseCard key={c.id} c={c} index={i} onOpen={() => open(c.id)} />)}
        </div>
      )}

      <div className="desk-data-note" style={{ marginTop: 24 }}>
        <span className="signal-dot" />
        Числа — это сообщения и публикации, а не количество людей. Система готовит данные, решение принимает сотрудник.
      </div>
    </div>
  )
}
