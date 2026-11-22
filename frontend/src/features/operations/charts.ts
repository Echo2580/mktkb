import type { EChartsCoreOption } from 'echarts/core';
import { RESULT_KINDS, RESULT_LABELS, type ResultKind } from './filters';

const AXIS_COLOR = '#e2e8f0';
const TEXT_COLOR = '#94a3b8';
const BLUE = '#2563eb';

/** 结果分布配色：按原型语义映射到 tokens.css 现有色值。 */
const RESULT_COLORS: Record<ResultKind, string> = {
  answer: '#2563eb', // --blue-600
  clarification: '#64748b', // --slate-500
  not_found: '#f59e0b', // --amber-500
  conflict: '#d97706', // --amber-600（橙色系）
  service_error: '#e11d48', // --rose-600
  knowledge_changed: '#10b981', // --emerald-500
};

export interface TrendPointView {
  date: string;
  completed: number;
  citations: number;
}

/** 问答趋势：平滑折线 + 自上而下面积渐变；空数组由页面渲染空态，不造假点。 */
export function trendOption(points: TrendPointView[], animation: boolean): EChartsCoreOption {
  return {
    animation,
    animationDuration: 320,
    grid: { left: 4, right: 12, top: 16, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0f172a',
      borderWidth: 0,
      padding: [7, 10],
      textStyle: { color: '#ffffff', fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: '#cbd5e1', type: 'dashed' } },
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = rows[0] as { axisValue?: string; value?: number } | undefined;
        return `<div style="font-size:12px;color:#cbd5e1">${first?.axisValue ?? ''}</div>
          <div style="margin-top:2px;font-size:13px;font-weight:600">${first?.value ?? 0} 条问答</div>
          <div style="margin-top:2px;font-size:11px;color:#94a3b8">点击查看明细</div>`;
      },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: points.map((point) => point.date.slice(5)),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisTick: { show: false },
      axisLabel: { color: TEXT_COLOR, fontSize: 11, margin: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitNumber: 4,
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: TEXT_COLOR, fontSize: 11 },
    },
    series: [
      {
        name: '完成问答',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: points.length <= 15,
        data: points.map((point) => point.completed),
        lineStyle: { width: 2, color: BLUE },
        itemStyle: { color: BLUE, borderColor: '#ffffff', borderWidth: 2 },
        emphasis: { scale: 1.4, itemStyle: { color: '#1d4ed8' } },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(37, 99, 235, 0.16)' },
              { offset: 1, color: 'rgba(37, 99, 235, 0.01)' },
            ],
          },
        },
      },
    ],
  };
}

/** 结果分布：横向条形图（6 类固定顺序）；条右显示数值，颜色按语义区分。 */
export function distributionOption(
  distribution: Partial<Record<ResultKind, number>>,
  animation: boolean,
): EChartsCoreOption {
  return {
    animation,
    animationDuration: 320,
    grid: { left: 4, right: 40, top: 6, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'item',
      backgroundColor: '#0f172a',
      borderWidth: 0,
      padding: [7, 10],
      textStyle: { color: '#ffffff', fontSize: 12 },
    },
    xAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: TEXT_COLOR, fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: RESULT_KINDS.map((kind) => RESULT_LABELS[kind]),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisTick: { show: false },
      axisLabel: { color: '#475569', fontSize: 12, margin: 10 },
    },
    series: [
      {
        name: '问答结果',
        type: 'bar',
        barWidth: 12,
        data: RESULT_KINDS.map((kind) => ({
          value: distribution[kind] ?? 0,
          itemStyle: { color: RESULT_COLORS[kind], borderRadius: [0, 4, 4, 0] },
        })),
        label: {
          show: true,
          position: 'right',
          color: '#64748b',
          fontSize: 11,
          formatter: '{c}',
        },
      },
    ],
  };
}
