import { DownloadOutlined } from '@ant-design/icons'
import { App, Button, Dropdown, Tag, Tooltip } from 'antd'
import dayjs from 'dayjs'
import type { ReactNode } from 'react'
import { download } from '../api'
import { C, GEO_COLOR, GEO_LABEL, KIND_LABEL, PLATFORM_COLOR, PLATFORM_LABEL, PRIO_COLOR, PRIO_LABEL, SENT_COLOR, SENT_LABEL, STATUS_COLOR, STATUS_LABEL, URGENCY_LABEL } from '../theme'

export function PageHead({ title, sub, extra }: { title: string; sub?: ReactNode; extra?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {extra && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{extra}</div>}
    </div>
  )
}

export function Panel({ title, note, extra, children, className, style }: {
  title?: ReactNode; note?: ReactNode; extra?: ReactNode; children: ReactNode; className?: string; style?: React.CSSProperties
}) {
  return (
    <section className={`panel ${className ?? ''}`} style={style}>
      {(title || extra) && (
        <div className="panel-head">
          <div>
            {title && <h2 className="panel-title">{title}</h2>}
            {note && <div className="panel-note">{note}</div>}
          </div>
          {extra}
        </div>
      )}
      {children}
    </section>
  )
}

export function SentimentTag({ value, score }: { value?: string | null; score?: number }) {
  if (!value) return <span className="muted">—</span>
  return (
    <Tag color={SENT_COLOR[value]} style={{ marginInlineEnd: 0 }}>
      {SENT_LABEL[value]}{score !== undefined ? ` ${score > 0 ? '+' : ''}${score.toFixed(1)}` : ''}
    </Tag>
  )
}

export function PriorityTag({ value, score }: { value?: string | null; score?: number }) {
  if (!value) return <span className="muted">—</span>
  return (
    <Tag color={PRIO_COLOR[value]} style={{ marginInlineEnd: 0, fontWeight: 700 }}>
      {PRIO_LABEL[value]}{score !== undefined ? ` · ${Math.round(score)}` : ''}
    </Tag>
  )
}

export function StatusTag({ value }: { value: string }) {
  return (
    <Tag style={{ marginInlineEnd: 0, borderColor: STATUS_COLOR[value], color: STATUS_COLOR[value], background: '#fff' }}>
      {STATUS_LABEL[value] ?? value}
    </Tag>
  )
}

export function UrgencyTags({ markers }: { markers: string[] }) {
  if (!markers?.length) return null
  return <>{markers.map((m) => (
    <Tag key={m} color={m === 'life_threat' || m === 'accident' ? 'red' : 'orange'} style={{ marginInlineEnd: 4 }}>
      {URGENCY_LABEL[m] ?? m}
    </Tag>
  ))}</>
}

export function Confidence({ value, threshold = 0.6 }: { value: number; threshold?: number }) {
  const color = value < threshold ? C.brick : value < 0.8 ? C.gold : C.green
  return (
    <Tooltip title={value < threshold ? `Ниже порога ${threshold} — требует проверки оператором` : 'Уверенность модели'}>
      <span className="conf">
        <span className="conf-bar"><i style={{ width: `${Math.round(value * 100)}%`, background: color }} /></span>
        {Math.round(value * 100)}%
      </span>
    </Tooltip>
  )
}

// Highlights masking tokens like [ФИО] so readers see that data was removed, not lost.
export function MaskedText({ text, clamp }: { text: string; clamp?: boolean }) {
  const parts = text.split(/(\[[А-ЯЁA-Z№]+\])/g)
  return (
    <span className={clamp ? 'msg-clamp' : 'msg'}>
      {parts.map((p, i) => (/^\[[А-ЯЁA-Z№]+\]$/.test(p)
        ? <Tooltip key={i} title="Персональные данные скрыты"><span className="mask">{p}</span></Tooltip>
        : <span key={i}>{p}</span>))}
    </span>
  )
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h4>{title}</h4>
      {children && <div style={{ maxWidth: 460, margin: '0 auto 12px' }}>{children}</div>}
      {action}
    </div>
  )
}

export const fmtDate = (s?: string | null) => (s ? dayjs(s).format('DD.MM.YYYY HH:mm') : '—')
export const fmtShort = (s?: string | null) => (s ? dayjs(s).format('DD.MM HH:mm') : '—')
export const fmtHours = (h?: number | null) => (h === null || h === undefined ? '—' : h < 48 ? `${Math.round(h)} ч` : `${(h / 24).toFixed(1)} дн`)

export function ExportMenu({ base, params, label = 'Экспорт', formats = ['xlsx', 'csv', 'pdf'] }: {
  base: string; params?: Record<string, string | undefined>; label?: string; formats?: string[]
}) {
  const { message } = App.useApp()
  const names: Record<string, string> = { xlsx: 'Excel (XLSX)', csv: 'CSV', pdf: 'PDF' }
  const run = async (fmt: string) => {
    const key = 'export'
    message.loading({ content: 'Готовим файл…', key })
    try {
      await download(`${base}.${fmt}`, params)
      message.success({ content: 'Файл скачан', key })
    } catch (e) {
      message.error({ content: (e as Error).message, key })
    }
  }
  return (
    <Dropdown menu={{ items: formats.map((f) => ({ key: f, label: names[f] })), onClick: ({ key }) => run(key) }}>
      <Button icon={<DownloadOutlined />}>{label}</Button>
    </Dropdown>
  )
}

export function PlatformTag({ value, kind }: { value: string; kind?: string }) {
  return (
    <Tag style={{ marginInlineEnd: 0, color: PLATFORM_COLOR[value] ?? C.muted, borderColor: PLATFORM_COLOR[value] ?? C.line, background: '#fff' }}>
      {PLATFORM_LABEL[value] ?? value}{kind && kind !== 'post' ? ` · ${KIND_LABEL[kind] ?? kind}` : ''}
    </Tag>
  )
}

export function GeoTag({ value, reviewed }: { value: string; reviewed?: boolean }) {
  return (
    <Tag style={{ marginInlineEnd: 0, color: GEO_COLOR[value], borderColor: GEO_COLOR[value], background: '#fff' }}>
      {GEO_LABEL[value] ?? value}{reviewed ? ' ✓' : ''}
    </Tag>
  )
}
