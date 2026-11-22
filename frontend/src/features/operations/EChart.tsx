import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsCoreOption, EChartsType } from 'echarts/core';

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

interface EChartProps {
  option: EChartsCoreOption;
  ariaLabel: string;
  testId: string;
  categoryCount: number;
  categoryAxis?: 'x' | 'y';
  onCategoryClick?: (index: number) => void;
}

/**
 * ECharts 容器：统一初始化、自适应和“点图表 = 点键盘等价按钮”的分类索引换算。
 * 点击与键盘按钮都回调同一个 onCategoryClick，避免两套下钻逻辑。
 */
export function EChart({
  option,
  ariaLabel,
  testId,
  categoryCount,
  categoryAxis = 'x',
  onCategoryClick,
}: EChartProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const clickRef = useRef(onCategoryClick);
  clickRef.current = onCategoryClick;
  const countRef = useRef(categoryCount);
  countRef.current = categoryCount;
  const axisRef = useRef(categoryAxis);
  axisRef.current = categoryAxis;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const chart = echarts.init(host, undefined, { renderer: 'canvas' });
    chartRef.current = chart;
    const resize = () => chart.resize();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    observer?.observe(host);
    window.addEventListener('resize', resize);

    const zr = chart.getZr();
    const handleClick = (event: { offsetX: number; offsetY: number }) => {
      const callback = clickRef.current;
      const total = countRef.current;
      const axis = axisRef.current;
      if (!callback || total <= 0) return;
      let index = Number.NaN;
      try {
        const point = chart.convertFromPixel({ seriesIndex: 0 }, [event.offsetX, event.offsetY]);
        if (Array.isArray(point)) index = Math.round(Number(axis === 'y' ? point[1] : point[0]));
      } catch {
        index = Number.NaN;
      }
      if (!Number.isFinite(index) || index < 0 || index >= total) {
        // 坐标轴外或换算失败时按绘图区比例兜底，保证点击总是可解释。
        if (axis === 'y') {
          const height = host.clientHeight;
          const ratio = Math.min(1, Math.max(0, (event.offsetY - 6) / Math.max(1, height - 10)));
          index = Math.round(ratio * (total - 1));
        } else {
          const width = host.clientWidth;
          const plotLeft = 48;
          const plotWidth = Math.max(1, width - 72);
          const ratio = Math.min(1, Math.max(0, (event.offsetX - plotLeft) / plotWidth));
          index = Math.round(ratio * (total - 1));
        }
      }
      if (index >= 0 && index < total) callback(index);
    };
    zr.on('click', handleClick);

    return () => {
      zr.off('click', handleClick);
      observer?.disconnect();
      window.removeEventListener('resize', resize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={hostRef} className="ops-chart-canvas" data-testid={testId} role="img" aria-label={ariaLabel} />;
}
