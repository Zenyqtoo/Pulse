import {
  AlertOutlined, ApartmentOutlined, AuditOutlined, CommentOutlined, DashboardOutlined, DatabaseOutlined, EnvironmentOutlined,
  ExperimentOutlined, LockOutlined, LogoutOutlined, MenuOutlined, MessageOutlined, SafetyCertificateOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Drawer, Dropdown, Grid, Layout, Menu, Tooltip } from 'antd'
import { useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../context'
import { ROLE_LABEL } from '../theme'
import ClusterDrawer from './ClusterDrawer'
import ItemDrawer from './ItemDrawer'

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="7" fill="#1E4468" />
      <path d="M5 17h5l3-7 4 13 3-9 2 3h5" fill="none" stroke="#5FB4EA" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
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

  const items = [
    { key: '/', icon: <DashboardOutlined />, label: 'Общая картина' },
    { key: '/problems', icon: <AlertOutlined />, label: 'Проблемы и приоритеты' },
    { key: '/departments', icon: <ApartmentOutlined />, label: 'Подразделения' },
    { key: '/feed', icon: <UnorderedListOutlined />, label: 'Лента обращений' },
    can('operator') && { key: '/review', icon: <SafetyCertificateOutlined />, label: <span>Проверка ИИ <Badge count={ops?.review_queue} size="small" offset={[6, -2]} color="#D9A21B" /></span> },
    can('operator') && { key: '/geo', icon: <EnvironmentOutlined />, label: <span>Геопривязка <Badge count={ops?.geo_queue} size="small" offset={[6, -2]} color="#D9A21B" /></span> },
    can('operator') && { key: '/direct', icon: <LockOutlined />, label: <span>Личные обращения <Badge count={ops?.new_direct} size="small" offset={[6, -2]} /></span> },
    { key: '/assistant', icon: <MessageOutlined />, label: 'ИИ-ассистент' },
    { type: 'divider' as const },
    { key: '/sources', icon: <DatabaseOutlined />, label: 'Источники и сбор' },
    { key: '/quality', icon: <ExperimentOutlined />, label: 'Качество ИИ' },
    can('admin') && { key: '/admin', icon: <AuditOutlined />, label: 'Администрирование' },
  ].filter(Boolean) as NonNullable<Parameters<typeof Menu>[0]['items']>

  const selected = '/' + (loc.pathname.split('/')[1] ?? '')
  const menu = (
    <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={items} style={{ borderInlineEnd: 0, padding: '8px 8px 120px' }}
      onClick={({ key }) => { nav(key); setMobileOpen(false) }} />
  )
  const footer = (
    <div className="sider-foot">
      <div><span className="dot" style={{ background: meta?.llm_enabled ? '#5BD08F' : '#E3A21A' }} />
        {meta?.llm_enabled ? `ИИ: ${meta.llm_model}` : 'ИИ: резервный режим (правила)'}</div>
      <div style={{ opacity: .7 }}>Векторы: {meta?.embedding_backend}</div>
    </div>
  )
  const brand = (
    <Link to="/" className="brand"><BrandMark /><span className="brand-name">Пульс города<span className="brand-sub">мониторинг обращений · {meta?.city_name}</span></span></Link>
  )

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {screens.lg ? (
        <Layout.Sider width={248} style={{ position: 'sticky', top: 0, height: '100vh', overflow: 'auto' }}>
          {brand}{menu}{footer}
        </Layout.Sider>
      ) : (
        <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} placement="left" size={260}
          styles={{ body: { padding: 0, background: '#13304D' }, header: { display: 'none' } }}>
          {brand}{menu}{footer}
        </Drawer>
      )}
      <Layout>
        <header className="topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {!screens.lg && <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileOpen(true)} aria-label="Меню" />}
            {ops && ops.overdue > 0 && (
              <Tooltip title="Новые обращения без реакции дольше 48 часов">
                <Link to="/feed?status=new&days=365" style={{ color: '#B8432F', fontSize: 13.5 }}>{ops.overdue}<span className="overdue-text"> без реакции дольше 48 ч</span></Link>
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
    </Layout>
  )
}
