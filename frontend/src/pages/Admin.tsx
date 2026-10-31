import { PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Form, Input, Modal, Select, Switch, Table, Tabs, Tag } from 'antd'
import { useState } from 'react'
import { api } from '../api'
import { fmtDate, PageHead } from '../components/ui'
import { useApp } from '../context'
import { ROLE_LABEL } from '../theme'
import type { User } from '../types'

export default function Admin() {
  return (
    <>
      <PageHead title="Администрирование" sub="Пользователи и роли, справочник подразделений и журнал действий" />
      <Tabs items={[
        { key: 'u', label: 'Пользователи', children: <Users /> },
        { key: 'd', label: 'Подразделения', children: <Depts /> },
        { key: 'a', label: 'Журнал действий', children: <Audit /> },
      ]} />
    </>
  )
}

const roleOpts = Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))

function Users() {
  const { meta, user: me } = useApp()
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [edit, setEdit] = useState<User | 'new' | null>(null)
  const [form] = Form.useForm()
  const { data, isLoading } = useQuery({ queryKey: ['users'], queryFn: () => api.get<User[]>('/api/users') })
  const patch = useMutation({ mutationFn: ({ id, body }: { id: number; body: object }) => api.patch(`/api/users/${id}`, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); message.success('Сохранено') }, onError: (e: Error) => message.error(e.message) })
  const deptOpts = [{ value: '', label: 'Весь город' }, ...(meta?.departments.map((d) => ({ value: d.code, label: d.name })) ?? [])]
  const save = async () => {
    const v = await form.validateFields()
    try {
      if (edit === 'new') await api.post('/api/users', { ...v, department_code: v.department_code || null })
      else if (edit) await api.patch(`/api/users/${edit.id}`, { full_name: v.full_name, role: v.role, department_code: v.department_code || null, ...(v.password ? { password: v.password } : {}) })
      qc.invalidateQueries({ queryKey: ['users'] }); setEdit(null); message.success('Пользователь сохранён')
    } catch (e) { message.error((e as Error).message) }
  }
  return (
    <>
      <div style={{ marginBottom: 12 }}><Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setEdit('new') }}>Добавить пользователя</Button></div>
      <div className="panel" style={{ padding: 0 }}>
        <Table<User> rowKey="id" loading={isLoading} dataSource={data} pagination={false} size="middle" scroll={{ x: 760 }}
          columns={[
            { title: 'Пользователь', dataIndex: 'full_name', render: (v, r) => <><b>{v}</b><div className="muted">{r.login}</div></> },
            { title: 'Роль', dataIndex: 'role', render: (v) => <Tag color={v === 'admin' ? 'geekblue' : v === 'operator' ? 'blue' : 'default'}>{ROLE_LABEL[v]}</Tag> },
            { title: 'Область видимости', dataIndex: 'department_code', render: (v) => v ? meta?.departments.find((d) => d.code === v)?.name : 'Весь город' },
            { title: 'Активен', dataIndex: 'active', render: (v, r) => <Switch size="small" checked={v} disabled={r.id === me?.id} onChange={(a) => patch.mutate({ id: r.id, body: { active: a } })} /> },
            { title: '', render: (_, r) => <Button size="small" onClick={() => { form.setFieldsValue({ ...r, department_code: r.department_code ?? '', password: '' }); setEdit(r) }}>Изменить</Button> },
          ]} />
      </div>
      <Modal open={!!edit} title={edit === 'new' ? 'Новый пользователь' : 'Изменить пользователя'} okText="Сохранить" cancelText="Отмена" onOk={save} onCancel={() => setEdit(null)} destroyOnHidden>
        <Form form={form} layout="vertical" requiredMark={false} initialValues={{ role: 'operator', department_code: '' }}>
          {edit === 'new' && <Form.Item name="login" label="Логин" rules={[{ required: true, pattern: /^[a-zA-Z0-9_.-]{3,}$/, message: 'Латиница, цифры, не короче 3 символов' }]}><Input autoComplete="off" /></Form.Item>}
          <Form.Item name="full_name" label="ФИО" rules={[{ required: true, min: 2, message: 'Укажите ФИО' }]}><Input /></Form.Item>
          <Form.Item name="role" label="Роль" extra="Наблюдатель видит дашборды и публичные обращения; оператор проверяет и маршрутизирует, видит личные обращения; администратор управляет системой.">
            <Select options={roleOpts} />
          </Form.Item>
          <Form.Item name="department_code" label="Область видимости" extra="Сотрудник подразделения видит только свою сферу (п. 3.8.6)."><Select options={deptOpts} /></Form.Item>
          <Form.Item name="password" label={edit === 'new' ? 'Пароль' : 'Новый пароль (необязательно)'}
            rules={edit === 'new' ? [{ required: true, min: 8, message: 'Не короче 8 символов' }] : [{ min: 8, message: 'Не короче 8 символов' }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

interface Dept { code: string; name: string; name_kk: string | null; description: string; keywords: string[] }

function Depts() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [edit, setEdit] = useState<Dept | 'new' | null>(null)
  const [form] = Form.useForm()
  const { data, isLoading } = useQuery({ queryKey: ['departments-admin'], queryFn: () => api.get<Dept[]>('/api/departments') })
  const save = async () => {
    const v = await form.validateFields()
    const code = edit === 'new' ? v.code : (edit as Dept).code
    try {
      await api.put(`/api/departments/${code}`, { name: v.name, name_kk: v.name_kk || null, description: v.description ?? '',
        keywords: String(v.keywords ?? '').split(',').map((s: string) => s.trim()).filter(Boolean) })
      qc.invalidateQueries({ queryKey: ['departments-admin'] }); qc.invalidateQueries({ queryKey: ['meta'] })
      setEdit(null); message.success('Справочник обновлён. Новые обращения будут классифицироваться с учётом изменений.')
    } catch (e) { message.error((e as Error).message) }
  }
  return (
    <>
      <div style={{ marginBottom: 12 }}><Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setEdit('new') }}>Добавить подразделение</Button></div>
      <div className="panel" style={{ padding: 0 }}>
        <Table<Dept> rowKey="code" loading={isLoading} dataSource={data} pagination={false} size="middle" scroll={{ x: 800 }}
          columns={[
            { title: 'Подразделение', dataIndex: 'name', width: 220, render: (v, r) => <><b>{v}</b><div className="muted">{r.name_kk} · {r.code}</div></> },
            { title: 'Сфера (передаётся модели)', dataIndex: 'description' },
            { title: 'Ключевые слова (резервный режим)', dataIndex: 'keywords', width: 280, render: (v: string[]) => <span className="muted msg-clamp">{v.join(', ')}</span> },
            { title: '', width: 100, render: (_, r) => <Button size="small" onClick={() => { form.setFieldsValue({ ...r, keywords: r.keywords.join(', ') }); setEdit(r) }}>Изменить</Button> },
          ]} />
      </div>
      <Modal open={!!edit} title={edit === 'new' ? 'Новое подразделение' : 'Изменить подразделение'} okText="Сохранить" cancelText="Отмена" onOk={save} onCancel={() => setEdit(null)} width={600} destroyOnHidden>
        <Form form={form} layout="vertical" requiredMark={false}>
          {edit === 'new' && <Form.Item name="code" label="Код (латиница)" rules={[{ required: true, pattern: /^[a-z0-9_]{2,40}$/, message: 'Строчная латиница, цифры, _' }]}><Input /></Form.Item>}
          <Form.Item name="name" label="Название" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
          <Form.Item name="name_kk" label="Название на казахском"><Input /></Form.Item>
          <Form.Item name="description" label="Сфера ответственности" extra="Этот текст получает модель при классификации."><Input.TextArea autoSize={{ minRows: 2 }} maxLength={1000} /></Form.Item>
          <Form.Item name="keywords" label="Ключевые слова через запятую" extra="Используются в резервном режиме без LLM."><Input.TextArea autoSize={{ minRows: 2 }} /></Form.Item>
        </Form>
      </Modal>
    </>
  )
}

const ACTION: Record<string, string> = {
  'auth.login': 'Вход', 'auth.failed': 'Неудачный вход', 'item.view_original': 'Просмотр оригинала', 'direct.view_masked': 'Просмотр Direct (маска)',
  'item.correct': 'Исправление ИИ', 'item.confirm': 'Подтверждение ИИ', 'item.reanalyze': 'Повторный анализ', 'item.delete': 'Удаление по запросу',
  'direct.reply': 'Ответ жителю', 'cluster.update': 'Изменение проблемы', 'cluster.recluster': 'Пересборка проблем', 'source.run': 'Запуск сбора',
  'source.upload': 'Загрузка файла', 'source.create': 'Новый источник', 'source.update': 'Изменение источника', 'source.delete': 'Удаление источника',
  'export.items': 'Экспорт обращений', 'export.clusters': 'Экспорт проблем', 'export.report': 'Сводка PDF', 'user.create': 'Новый пользователь',
  'user.update': 'Изменение пользователя', 'department.save': 'Справочник подразделений', 'gold.label': 'Разметка', 'gold.import': 'Импорт разметки',
  'quality.evaluate': 'Оценка качества', 'assistant.ask': 'Вопрос ассистенту', 'pipeline.process': 'Анализ очереди',
}

function Audit() {
  const [action, setAction] = useState<string | undefined>()
  const { data, isLoading } = useQuery({ queryKey: ['audit', action], queryFn: () => api.get<{ id: number; at: string; user: string; action: string; entity: string | null; entity_id: string | null; details: Record<string, unknown> }[]>('/api/audit', { action, limit: 500 }) })
  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="Все действия" style={{ width: 280 }} value={action} onChange={setAction} aria-label="Тип действия"
          options={[{ value: 'item.view_original', label: 'Просмотры оригиналов' }, { value: 'direct', label: 'Действия с Direct' },
            { value: 'item.', label: 'Работа с обращениями' }, { value: 'export', label: 'Экспорт' }, { value: 'auth', label: 'Входы' },
            { value: 'source', label: 'Источники' }, { value: 'user', label: 'Пользователи' }]} />
      </div>
      <div className="panel" style={{ padding: 0 }}>
        <Table rowKey="id" loading={isLoading} dataSource={data} size="small" pagination={{ pageSize: 20, showSizeChanger: false }} scroll={{ x: 760 }}
          columns={[
            { title: 'Время', dataIndex: 'at', width: 150, render: fmtDate },
            { title: 'Пользователь', dataIndex: 'user', width: 220 },
            { title: 'Действие', dataIndex: 'action', width: 220, render: (v) => ACTION[v] ?? v },
            { title: 'Объект', render: (_, r) => r.entity ? `${r.entity} №${r.entity_id}` : '—', width: 120 },
            { title: 'Детали', dataIndex: 'details', render: (v) => <span className="muted" style={{ fontSize: 12.5 }}>{Object.keys(v ?? {}).length ? JSON.stringify(v).slice(0, 160) : ''}</span> },
          ]} />
      </div>
    </>
  )
}
