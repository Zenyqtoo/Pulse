import {
  AlertOutlined, ApartmentOutlined, AppstoreOutlined, AuditOutlined, CommentOutlined, DashboardOutlined, DatabaseOutlined, EnvironmentOutlined,
  ExperimentOutlined, LockOutlined, LogoutOutlined, MenuOutlined, MessageOutlined, SafetyCertificateOutlined, UnorderedListOutlined, BarChartOutlined, SettingOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Drawer, Dropdown, Grid, Layout, Menu, Tooltip } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../context'
import { ROLE_LABEL } from '../theme'
import ClusterDrawer from './ClusterDrawer'
import ItemDrawer from './ItemDrawer'
import DecisionDrawer from './DecisionDrawer'

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="10" fill="#D8F475" />
      <circle cx="16" cy="16" r="8" fill="none" stroke="#183D36" strokeWidth="2" />
      <path d="M16 6v5M16 21v5M6 16h5M21 16h5" stroke="#183D36" strokeWidth="2" />
      <circle cx="16" cy="16" r="2.5" fill="#183D36" />
    </svg>
  )
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const { user, meta, logout, can } = useApp()
  const loc = useLocation()
  const nav = useNavigate()
  const screens = Grid.useBreakpoint()
  const [mobileOpen, setMobileOpen] = useState(false)
  const { data: ops } = useQuery({
    queryKey: ['ops'], queryFn: () => api.get<{ review_queue: number; geo_queue: number; new_direct: number; overdue: number }>('/api/stats/operations'),
    refetchInterval: 30_000,
  })

  const badge = (n?: number, color?: string) => n ? <Badge count={n} size="small" overflowCount={99} color={color} style={{ marginInlineStart: 8, boxShadow: 'none' }} /> : null
  // Four everyday sections stay flat; queues appear only for roles that work them; the rest is folded away.
  const items = [
    { key: '/', icon: <DashboardOutlined />, label: 'Требует внимания' },
    { key: '/problems', icon: <AlertOutlined />, label: 'Все проблемы' },
    { key: '/feed', icon: <UnorderedListOutlined />, label: 'Обращения жителей' },
    { key: '/analytics', icon: <BarChartOutlined />, label: 'Аналитика' },
    can('operator') && { type: 'group' as const, key: 'queues', label: 'Мои очереди', children: [
      { key: '/review', icon: <SafetyCertificateOutlined />, label: <span>Выводы ИИ{badge(ops?.review_queue, '#C9922A')}</span> },
      { key: '/geo', icon: <EnvironmentOutlined />, label: <span>Уточнить место{badge(ops?.geo_queue, '#C9922A')}</span> },
      { key: '/direct', icon: <LockOutlined />, label: <span>Личные обращения{badge(ops?.new_direct)}</span> },
    ] },
    { key: 'more', icon: <AppstoreOutlined />, label: 'Ещё', children: [
      { key: '/defense', icon: <SafetyCertificateOutlined />, label: 'Сценарии для защиты' },
      { key: '/departments', icon: <ApartmentOutlined />, label: 'Подразделения' },
      { key: '/assistant', icon: <MessageOutlined />, label: 'Спросить ассистента' },
      can('operator') && { key: '/quality', icon: <ExperimentOutlined />, label: 'Качество анализа' },
    ].filter(Boolean) },
    can('admin') && { key: 'admin', icon: <SettingOutlined />, label: 'Управление', children: [
      { key: '/sources', icon: <DatabaseOutlined />, label: 'Источники и сбор' },
      { key: '/admin', icon: <AuditOutlined />, label: 'Пользователи и журнал' },
    ] },
  ].filter(Boolean) as NonNullable<Parameters<typeof Menu>[0]['items']>

  const selected = '/' + (loc.pathname.split('/')[1] ?? '')
  const parent = ['/departments', '/assistant', '/quality', '/defense'].includes(selected) ? 'more' : ['/sources', '/admin'].includes(selected) ? 'admin' : null
  const [open, setOpen] = useState<string[]>(parent ? [parent] : [])
  useEffect(() => { if (parent) setOpen((o) => o.includes(parent) ? o : [...o, parent]) }, [parent])
  const menu = (
    <Menu theme="dark" mode="inline" selectedKeys={[selected]} openKeys={open} onOpenChange={setOpen} items={items}
      className="side-menu" style={{ borderInlineEnd: 0, padding: '4px 10px 132px' }}
      onClick={({ key }) => { nav(key); setMobileOpen(false) }} />
  )
  const footer = (
    <div className="sider-foot">
      <div><span className="dot" style={{ background: meta?.llm_enabled ? '#5BD08F' : '#E3A21A' }} />
        {meta?.llm_enabled ? 'Анализ с помощью ИИ' : 'Анализ по правилам'}</div>
      <div style={{ opacity: .7, marginTop: 8 }}>Система готовит факты.<br />Решение принимает сотрудник.</div>
    </div>
  )
  const brand = (
    <Link to="/" className="brand"><BrandMark /><span className="brand-name">City Alert<span className="brand-sub">Обращения жителей. Приоритеты города.</span></span></Link>
  )

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {screens.lg ? (
        <Layout.Sider width={246} style={{ position: 'sticky', top: 0, height: '100vh', overflow: 'auto' }}>
          {brand}{menu}{footer}
        </Layout.Sider>
      ) : (
        <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} placement="left" size={260}
          styles={{ body: { padding: 0, background: '#183D36' }, header: { display: 'none' } }}>
          {brand}{menu}{footer}
        </Drawer>
      )}
      <Layout>
        <header className="topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {!screens.lg && <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileOpen(true)} aria-label="Меню" />}
            <span className="workspace-label">{!screens.lg ? 'City Alert' : `${meta?.city_name ?? 'Павлодар'} · рабочее место сотрудника`}</span>
            {ops && ops.overdue > 0 && can('operator') && (
              <Tooltip title="Новые обращения без реакции дольше 48 часов">
                <Link className="overdue-link" to="/feed?status=new&days=365&voice=resident">Без реакции 48 ч+: {ops.overdue}</Link>
              </Tooltip>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Tooltip title="Спросить ИИ-ассистента"><Button type="text" icon={<CommentOutlined />} onClick={() => nav('/assistant')} aria-label="ИИ-ассистент" /></Tooltip>
            <Dropdown menu={{ items: [{ key: 'out', icon: <LogoutOutlined />, label: 'Выйти', onClick: logout }] }}>
              <Button type="text" style={{ height: 'auto', textAlign: 'right', lineHeight: 1.2, padding: '4px 8px' }}>
                <div className="user-name" style={{ fontWeight: 700 }}>{user?.full_name}</div>
                <div className="muted" style={{ fontSize: 12 }}>{ROLE_LABEL[user?.role ?? 'viewer']}{user?.department_code ? ` · ${meta?.departments.find((d) => d.code === user.department_code)?.name}` : ''}</div>
              </Button>
            </Dropdown>
          </div>
        </header>
        <main className="page">{children}</main>
      </Layout>
      <ItemDrawer />
      <ClusterDrawer />
      <DecisionDrawer />
    </Layout>
  )
}
