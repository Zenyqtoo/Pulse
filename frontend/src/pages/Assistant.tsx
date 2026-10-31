import { SendOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { Alert, Button, Input, Spin, Tag } from 'antd'
import { Fragment, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { MaskedText, PageHead, Panel, SentimentTag, fmtShort } from '../components/ui'
import { useApp } from '../context'

interface Answer {
  answer: string; model: string; total: number; filters: Record<string, string | number>
  items: { id: number; text: string; published_at: string; department: string; sentiment: string; url: string | null }[]
}
interface Turn { q: string; a?: Answer; error?: string }

const SUGGEST = [
  'Какие главные жалобы по ЖКХ за последнюю неделю?',
  'Покажи негатив по школам и детским садам',
  'Что беспокоит жителей сегодня?',
  'Есть ли угрозы жизни или аварии за последние сутки?',
]

export default function Assistant() {
  const [q, setQ] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [, setSp] = useSearchParams()
  const { meta, deptName } = useApp()
  const open = (key: 'item' | 'problem', id: string) => setSp((p) => { const n = new URLSearchParams(p); n.set(key, id); return n })
  const ask = useMutation({
    mutationFn: (question: string) => api.post<Answer>('/api/assistant/ask', { question }),
    onSuccess: (a, question) => setTurns((t) => t.map((x) => (x.q === question && !x.a && !x.error ? { ...x, a } : x))),
    onError: (e: Error, question) => setTurns((t) => t.map((x) => (x.q === question && !x.a ? { ...x, error: e.message } : x))),
  })
  const submit = (text: string) => {
    const question = text.trim()
    if (question.length < 3 || ask.isPending) return
    setTurns((t) => [...t, { q: question }])
    setQ('')
    ask.mutate(question)
  }
  // Turns [#12] and [P#3] references into links that open the record
  const render = (text: string) => text.split(/(\[P?#\d+\])/g).map((part, i) => {
    const m = /^\[(P?)#(\d+)\]$/.exec(part)
    if (!m) return <Fragment key={i}>{part}</Fragment>
    return <span key={i} className="ref" role="link" tabIndex={0} onClick={() => open(m[1] ? 'problem' : 'item', m[2])}
      onKeyDown={(e) => e.key === 'Enter' && open(m[1] ? 'problem' : 'item', m[2])}>{part}</span>
  })

  return (
    <>
      <PageHead title="ИИ-ассистент" sub="Вопросы на естественном языке по собранным обращениям. Ответы ссылаются на исходные обращения [#номер] и проблемы [P#номер]." />
      {!meta?.llm_enabled && (
        <Alert type="warning" showIcon style={{ marginBottom: 14 }} title="Ключ Claude API не задан"
          description="Ассистент работает в резервном режиме: подбирает обращения и проблемы по правилам и показывает их без пересказа. Добавьте ANTHROPIC_API_KEY в .env для полноценных ответов." />
      )}
      <div style={{ maxWidth: 920 }}>
        {turns.length === 0 && (
          <Panel title="С чего начать">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {SUGGEST.map((s) => <Button key={s} onClick={() => submit(s)}>{s}</Button>)}
            </div>
          </Panel>
        )}
        {turns.map((t, i) => (
          <div key={i} style={{ marginTop: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 8 }}>{t.q}</div>
            <Panel>
              {!t.a && !t.error && <Spin description="Ищем обращения и готовим ответ…" />}
              {t.error && <Alert type="error" showIcon title={t.error} />}
              {t.a && (
                <>
                  <div className="chat-answer">{render(t.a.answer)}</div>
                  <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
                    Найдено обращений: {t.a.total} · фильтры:{' '}
                    {Object.entries(t.a.filters).length ? Object.entries(t.a.filters).map(([k, v]) =>
                      <Tag key={k}>{k === 'department' ? deptName(String(v)) : k === 'days' ? `${v} дн.` : String(v)}</Tag>) : 'нет'}
                    · ответ: {t.a.model}
                  </div>
                  {t.a.items.length > 0 && (
                    <>
                      <div className="section-label">Исходные обращения</div>
                      {t.a.items.slice(0, 8).map((it) => (
                        <div key={it.id} className="prob" style={{ gridTemplateColumns: '56px minmax(0,1fr) auto' }} onClick={() => open('item', String(it.id))}>
                          <span className="ref">#{it.id}</span>
                          <div><MaskedText text={it.text} clamp /><div className="prob-meta">{fmtShort(it.published_at)} · {deptName(it.department)}</div></div>
                          <SentimentTag value={it.sentiment} />
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
            </Panel>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 8, marginTop: 18, position: 'sticky', bottom: 16 }}>
          <Input.TextArea value={q} onChange={(e) => setQ(e.target.value)} autoSize={{ minRows: 1, maxRows: 4 }} maxLength={500}
            placeholder="Например: какие проблемы с транспортом за последнюю неделю?" aria-label="Вопрос ассистенту"
            onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); submit(q) } }} style={{ fontSize: 15 }} />
          <Button type="primary" icon={<SendOutlined />} onClick={() => submit(q)} loading={ask.isPending} disabled={q.trim().length < 3}>Спросить</Button>
        </div>
      </div>
    </>
  )
}
