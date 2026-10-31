import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

const base = {
  textStyle: { fontFamily: "'PT Sans', sans-serif", color: '#1B2733' },
  grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
  tooltip: { backgroundColor: '#13304D', borderWidth: 0, textStyle: { color: '#fff', fontSize: 13 } },
}

export default function Chart({ option, height = 280, onClick }: {
  option: EChartsOption; height?: number; onClick?: (p: { name: string; seriesName?: string; data: unknown; dataIndex: number }) => void
}) {
  return (
    <ReactECharts
      option={{ ...base, ...option, tooltip: { ...base.tooltip, ...(option.tooltip as object) } }}
      style={{ height, width: '100%', cursor: onClick ? 'pointer' : 'default' }}
      notMerge
      onEvents={onClick ? { click: onClick } : undefined}
      opts={{ renderer: 'svg' }}
    />
  )
}
