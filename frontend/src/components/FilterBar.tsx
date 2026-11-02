import { ClearOutlined, FilterOutlined, SearchOutlined } from '@ant-design/icons'
import { Button, DatePicker, Input, Select, Switch, Tooltip } from 'antd'
import dayjs from 'dayjs'
import { useEffect, useState } from 'react'
import { useApp } from '../context'
import { useFilters, type FilterKey } from '../filters'
import { PRIO_LABEL, SENT_LABEL, STATUS_LABEL, TYPE_LABEL } from '../theme'

const opts = (m: Record<string, string>) => Object.entries(m).map(([value, label]) => ({ value, label }))
const multi = (v?: string) => (v ? v.split(',') : [])

type Field = 'period' | 'platform' | 'source' | 'department' | 'sentiment' | 'priority' | 'status' | 'type' | 'district' | 'q' | 'urgent' | 'origin' | 'voice'
const ALL: Field[] = ['period', 'q', 'platform', 'department', 'sentiment', 'priority', 'status', 'source', 'district', 'type', 'urgent', 'origin', 'voice']

export default function FilterBar({ fields = ALL }: { fields?: Field[] }) {
  const { meta, user } = useApp()
  const { filters, setFilters, reset, activeCount } = useFilters()
  const [q, setQ] = useState(filters.q ?? '')
  const secondaryActive = !!(filters.source || filters.district || filters.type || filters.origin || filters.voice || filters.urgent)
  const [more, setMore] = useState(secondaryActive)
  const SECONDARY: Field[] = ['source', 'district', 'type', 'origin', 'voice', 'urgent']
  const hasSecondary = fields.some((f) => SECONDARY.includes(f))
  useEffect(() => setQ(filters.q ?? ''), [filters.q])
  const has = (f: Field) => fields.includes(f) && (!SECONDARY.includes(f) || more || secondaryActive || fields.length <= 6)
  const set = (k: FilterKey) => (v: string[] | string | undefined) =>
    setFilters({ [k]: Array.isArray(v) ? v.join(',') : v } as Record<FilterKey, string>)
  const periodValue = filters.date_from ? 'custom' : filters.days ?? '30'

  return (
    <div className="filterbar" role="search" aria-label="Фильтры">
      {has('period') && (
        <>
          <Select aria-label="Период" value={periodValue} style={{ minWidth: 150 }}
            onChange={(v) => v !== 'custom' && setFilters({ days: v })}
            options={[{ value: '1', label: 'За сутки' }, { value: '7', label: 'За 7 дней' }, { value: '30', label: 'За 30 дней' },
              { value: '90', label: 'За 90 дней' }, { value: '365', label: 'За год' }, { value: 'custom', label: 'Свой период', disabled: true }]} />
          <DatePicker.RangePicker aria-label="Даты" format="DD.MM.YYYY" allowClear
            value={filters.date_from ? [dayjs(filters.date_from), filters.date_to ? dayjs(filters.date_to) : null] : null}
            onChange={(r) => r?.[0]
              ? setFilters({ date_from: r[0].startOf('day').toISOString(), date_to: r[1]?.endOf('day').toISOString() })
              : setFilters({ date_from: undefined, date_to: undefined, days: '30' })} />
        </>
      )}
      {has('q') && (
        <Input aria-label="Поиск по тексту" allowClear prefix={<SearchOutlined />} placeholder="Поиск по тексту, адресу, проблеме"
          style={{ width: 260 }} value={q} onChange={(e) => { setQ(e.target.value); if (!e.target.value) setFilters({ q: undefined }) }}
          onPressEnter={() => setFilters({ q: q.trim() || undefined })} />
      )}
      {has('platform') && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Платформа" aria-label="Платформа"
          value={multi(filters.platform)} onChange={set('platform')} style={{ minWidth: 160 }}
          options={Object.entries(meta?.platforms ?? {}).filter(([k]) => k !== 'other').map(([value, label]) => ({ value, label }))} />
      )}
      {has('department') && !user?.department_code && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Подразделение" aria-label="Подразделение"
          value={multi(filters.department)} onChange={set('department')}
          options={meta?.departments.map((d) => ({ value: d.code, label: d.name }))} style={{ minWidth: 190 }} />
      )}
      {has('sentiment') && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Тональность" aria-label="Тональность"
          value={multi(filters.sentiment)} onChange={set('sentiment')} options={opts(SENT_LABEL)} />
      )}
      {has('priority') && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Приоритет" aria-label="Приоритет"
          value={multi(filters.priority)} onChange={set('priority')} options={opts(PRIO_LABEL)} />
      )}
      {has('status') && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Статус" aria-label="Статус"
          value={multi(filters.status)} onChange={set('status')} options={opts(STATUS_LABEL)} />
      )}
      {has('source') && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Источник" aria-label="Источник"
          value={multi(filters.source)} onChange={set('source')} style={{ minWidth: 170 }}
          options={meta?.sources.map((s) => ({ value: String(s.id), label: s.name }))} />
      )}
      {has('district') && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Район" aria-label="Район" showSearch
          value={multi(filters.district)} onChange={set('district')} options={meta?.districts.map((d) => ({ value: d, label: d }))} />
      )}
      {has('type') && (
        <Select mode="multiple" allowClear maxTagCount="responsive" placeholder="Тип обращения" aria-label="Тип"
          value={multi(filters.type)} onChange={set('type')} options={opts(TYPE_LABEL)} />
      )}
      {has('origin') && (
        <Select allowClear placeholder="Данные" aria-label="Происхождение данных" value={filters.origin} onChange={set('origin')}
          style={{ minWidth: 150 }}
          options={[{ value: 'real', label: 'Только реальные' }, { value: 'synthetic', label: 'Только демо-набор' }]} />
      )}
      {has('voice') && (
        <Select allowClear placeholder="Кто пишет" aria-label="Кто пишет" value={filters.voice} onChange={set('voice')}
          style={{ minWidth: 170 }}
          options={[{ value: 'resident', label: 'Жители' }, { value: 'media', label: 'СМИ и официальные каналы' }]} />
      )}
      {has('urgent') && (
        <Tooltip title="Только обращения с маркерами срочности: авария, угроза жизни, нет воды/тепла, дети, пожилые">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13.5 }}>
            <Switch size="small" checked={filters.urgent === 'true'} onChange={(v) => setFilters({ urgent: v ? 'true' : undefined })} />
            Срочные
          </span>
        </Tooltip>
      )}
      {hasSecondary && fields.length > 6 && !secondaryActive && (
        <Button type="text" icon={<FilterOutlined />} onClick={() => setMore(!more)} aria-expanded={more}>
          {more ? 'Меньше фильтров' : 'Ещё фильтры'}
        </Button>
      )}
      {activeCount > 0 && (
        <Button type="text" icon={<ClearOutlined />} onClick={reset}>Сбросить</Button>
      )}
    </div>
  )
}
