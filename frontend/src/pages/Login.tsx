import { Alert, Button, Form, Input } from 'antd'
import { useState } from 'react'
import { useApp } from '../context'

export default function Login() {
  const { login } = useApp()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const submit = async (v: { login: string; password: string }) => {
    setLoading(true)
    setError(null)
    try { await login(v.login.trim(), v.password) } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  return (
    <div className="login-wrap">
      <div className="login-side">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <svg width="40" height="40" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="10" fill="#D8F475" />
            <circle cx="16" cy="16" r="8" fill="none" stroke="#183D36" strokeWidth="2" /><path d="M16 6v5M16 21v5M6 16h5M21 16h5" stroke="#183D36" strokeWidth="2" /><circle cx="16" cy="16" r="2.5" fill="#183D36" /></svg>
          <span style={{ fontFamily: 'Unbounded', fontWeight: 600, fontSize: 18 }}>City Alert</span>
        </div>
        <div>
          <h1>Что беспокоит жителей сегодня — и кто должен это решить</h1>
          <p>Система собирает обращения из открытых городских источников и личных сообщений в аккаунты акимата,
            определяет подразделение и тональность, объединяет похожие жалобы в проблемы и считает приоритет.
            Решения ИИ — рекомендации; итоговое решение принимает сотрудник.</p>
        </div>
        <p style={{ fontSize: 13 }}>Персональные данные маскируются до анализа. Доступ к личным обращениям — только по роли, каждый просмотр записывается.</p>
      </div>
      <div className="login-form">
        <h2 style={{ fontSize: 24, margin: '0 0 4px' }}>Вход для сотрудников</h2>
        <p className="muted" style={{ marginTop: 0, marginBottom: 24 }}>Используйте учётную запись, выданную администратором.</p>
        {error && <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
          <Form.Item name="login" label="Логин" rules={[{ required: true, message: 'Введите логин' }]}>
            <Input autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label="Пароль" rules={[{ required: true, message: 'Введите пароль' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>Войти</Button>
        </Form>
        <div className="muted" style={{ fontSize: 13, marginTop: 24, lineHeight: 1.6 }}>
          Учётные записи для демонстрации: <b>operator</b>, <b>admin</b>, <b>viewer</b>. Пароли задаются в файле .env (SEED_*_PASSWORD).
        </div>
      </div>
    </div>
  )
}
