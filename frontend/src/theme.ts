import type { ThemeConfig } from 'antd'

export const C = {
  ink: '#13304D',
  inkSoft: '#1E4468',
  sky: '#1F7FC1',
  skyTint: '#E6F1FA',
  paper: '#F4F6F8',
  line: '#DDE3EA',
  text: '#1B2733',
  muted: '#5C6B7A',
  brick: '#B8432F',
  gold: '#D9A21B',
  green: '#2F8A5B',
  slate: '#8C98A6',
}

export const SENT_COLOR: Record<string, string> = { positive: C.green, neutral: C.slate, negative: C.brick }
export const PRIO_COLOR: Record<string, string> = { high: C.brick, medium: C.gold, low: C.slate }
export const STATUS_COLOR: Record<string, string> = {
  new: '#1F7FC1', transferred: '#6B5FB5', in_progress: '#D9A21B', resolved: '#2F8A5B', closed: '#8C98A6',
}

export const SENT_LABEL: Record<string, string> = { positive: 'Положительная', neutral: 'Нейтральная', negative: 'Отрицательная' }
export const PRIO_LABEL: Record<string, string> = { high: 'Высокий', medium: 'Средний', low: 'Низкий' }
export const STATUS_LABEL: Record<string, string> = {
  new: 'Новое', transferred: 'Передано', in_progress: 'В работе', resolved: 'Решено', closed: 'Закрыто',
}
export const TYPE_LABEL: Record<string, string> = {
  complaint: 'Жалоба', question: 'Вопрос', proposal: 'Предложение', gratitude: 'Благодарность', info: 'Информация',
}
export const URGENCY_LABEL: Record<string, string> = {
  accident: 'Авария', life_threat: 'Угроза жизни', no_water: 'Нет воды', no_heat: 'Нет тепла',
  no_power: 'Нет электричества', children: 'Дети', elderly: 'Пожилые',
}
export const PLATFORM_LABEL: Record<string, string> = {
  telegram: 'Telegram', instagram: 'Instagram', threads: 'Threads', news: 'Новости и RSS', direct: 'Direct',
  upload: 'Загрузки', demo: 'Демо-набор', other: 'Другое',
}
export const PLATFORM_COLOR: Record<string, string> = {
  telegram: '#2A9FD8', instagram: '#C1358A', threads: '#1B2733', news: '#6B5FB5', direct: '#7A4FB8',
  upload: '#8C98A6', demo: '#AEB8C4', other: '#AEB8C4',
}
export const KIND_LABEL: Record<string, string> = {
  post: 'пост', comment: 'комментарий', reply: 'ответ', message: 'личное сообщение', article: 'статья', review: 'отзыв',
}
export const GEO_LABEL: Record<string, string> = { local: 'Павлодар', possible: 'Возможно Павлодар', not_local: 'Не Павлодар' }
export const GEO_COLOR: Record<string, string> = { local: '#2F8A5B', possible: '#D9A21B', not_local: '#8C98A6' }
export const SCOPE_LABEL: Record<string, string> = {
  city: 'Город Павлодар', region: 'Павлодарская область', national: 'Весь Казахстан', unknown: 'Охват не указан',
}

export const LANG_LABEL: Record<string, string> = { ru: 'Русский', kk: 'Казахский', mixed: 'Смешанный', other: 'Другой' }
export const ROLE_LABEL: Record<string, string> = { admin: 'Администратор', operator: 'Оператор', viewer: 'Наблюдатель' }
export const PII_LABEL: Record<string, string> = {
  iin: 'ИИН', phone: 'телефон', email: 'e-mail', card: 'карта', name: 'ФИО', apartment: 'квартира', house_number: 'номер дома',
}

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: C.sky,
    colorInfo: C.sky,
    colorSuccess: C.green,
    colorWarning: C.gold,
    colorError: C.brick,
    colorText: C.text,
    colorTextSecondary: C.muted,
    colorBorder: C.line,
    colorBorderSecondary: '#E8ECF1',
    colorBgLayout: C.paper,
    fontFamily: "'PT Sans', 'Segoe UI', system-ui, sans-serif",
    fontSize: 14,
    borderRadius: 6,
    borderRadiusLG: 8,
    controlHeight: 34,
  },
  components: {
    Layout: { siderBg: C.ink, headerBg: '#FFFFFF', bodyBg: C.paper },
    Menu: {
      darkItemBg: C.ink, darkSubMenuItemBg: C.ink, darkItemSelectedBg: C.inkSoft,
      darkItemColor: 'rgba(255,255,255,0.72)', darkItemSelectedColor: '#FFFFFF', itemBorderRadius: 4,
    },
    Table: { headerBg: '#F7F9FB', headerColor: C.muted, rowHoverBg: '#F2F7FC', cellPaddingBlock: 10 },
    Card: { headerFontSize: 15 },
    Tag: { defaultBg: '#F1F4F7' },
  },
}
