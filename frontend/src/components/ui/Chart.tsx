import { useState, useEffect, useRef, useCallback } from 'react';
import type { ReactNode } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, LabelList, ReferenceLine,
  LineChart, Line, Area, AreaChart,
  ComposedChart, PieChart, Pie, Cell, Sector
} from 'recharts';

// ── Color palette ──────────────────────────────────────────────
// CSS variable references — resolved via :root in index.css (OKLCH, more vibrant)
export const CHART_COLORS = {
  primary: 'var(--chart-1)',
  secondary: 'var(--chart-2)',
  accent: 'var(--chart-3)',
  warning: 'var(--chart-4)',
  danger: 'var(--chart-5)',
  teal: 'var(--chart-6)',
  pink: 'var(--chart-7)',
  orange: 'var(--chart-8)',
} as const;

export const CHART_SEQUENCE = [
  CHART_COLORS.primary,
  CHART_COLORS.secondary,
  CHART_COLORS.accent,
  CHART_COLORS.warning,
  CHART_COLORS.teal,
  CHART_COLORS.pink,
  CHART_COLORS.orange,
  CHART_COLORS.danger,
];

// Hex fallbacks for contexts where CSS vars don't resolve (exports, SSR)
export const CHART_COLORS_HEX = {
  primary: '#e76e50',
  secondary: '#2a9d8f',
  accent: '#264653',
  warning: '#e9c46a',
  danger: '#f4a261',
  teal: '#2cc7a0',
  pink: '#d63384',
  orange: '#e8590c',
} as const;

// ── Formatters ─────────────────────────────────────────────────
export const FORMATTERS = {
  brl: (v: number) =>
    v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }),
  percent: (v: number) => `${v.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`,
  number: (v: number) => v.toLocaleString('pt-BR'),
  compact: (v: number) => {
    if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
    return String(v);
  },
} as const;

// ── Shared internals ───────────────────────────────────────────

const BORDER_RADIUS = 8;

// Map CSS var → hex for luminance calculations
const VAR_TO_HEX: Record<string, string> = {
  'var(--chart-1)': CHART_COLORS_HEX.primary,
  'var(--chart-2)': CHART_COLORS_HEX.secondary,
  'var(--chart-3)': CHART_COLORS_HEX.accent,
  'var(--chart-4)': CHART_COLORS_HEX.warning,
  'var(--chart-5)': CHART_COLORS_HEX.danger,
  'var(--chart-6)': CHART_COLORS_HEX.teal,
  'var(--chart-7)': CHART_COLORS_HEX.pink,
  'var(--chart-8)': CHART_COLORS_HEX.orange,
};

/** Returns true if a color is dark (needs white text on top) */
function isDarkColor(color: string): boolean {
  const hex = VAR_TO_HEX[color] || color;
  const m = hex.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
  if (!m) return false;
  const r = parseInt(m[1], 16) / 255;
  const g = parseInt(m[2], 16) / 255;
  const b = parseInt(m[3], 16) / 255;
  // Relative luminance (WCAG formula)
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum < 0.45;
}

// Shadcn-style axis defaults: no axis line, no tick lines, clean minimal text
const AXIS_STYLE = { axisLine: false, tickLine: false, tickMargin: 10, fontSize: 12 } as const;

function ChartTooltip({ active, payload, label, formatter, hideLabel }: any) {
  if (!active || !payload?.length) return null;

  // Deduplicate entries (Recharts can send duplicates for stacked charts)
  const deduped = (() => {
    const seen = new Set<string>();
    return payload.filter((entry: any) => {
      const key = entry.dataKey ?? entry.name;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  })();

  const formatValue = (value: number) => {
    if (formatter) return formatter(value);
    return value?.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  return (
    <div className="min-w-[8rem] rounded-lg border bg-[var(--color-surface)] py-1.5 px-2.5 text-meta shadow-xl" style={{ borderColor: 'color-mix(in srgb, var(--color-border) 50%, transparent)' }}>
      {!hideLabel && label != null && (
        <div className="mb-1.5 font-medium" style={{ color: 'var(--color-text)' }}>{label}</div>
      )}
      <div className="flex flex-col gap-1.5">
        {deduped.map((entry: any, i: number) => (
          <div key={i} className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: entry.color }} />
              <span style={{ color: 'var(--color-text-secondary)' }}>{entry.name}</span>
            </div>
            <span className="font-mono font-medium tabular-nums" style={{ color: 'var(--color-text)' }}>
              {formatValue(entry.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const LEGEND_VISIBLE_LINES = 3;
const LEGEND_MAX_H_EXPANDED = 300;

function ChartLegend({ payload }: any) {
  const [expanded, setExpanded] = useState(false);
  const measureRef = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [hiddenCount, setHiddenCount] = useState(0);
  const [collapsedH, setCollapsedH] = useState(60); // recalculado dinamicamente

  useEffect(() => {
    const el = measureRef.current;
    if (!el) return;
    const check = () => {
      if (!measureRef.current) return;
      // Remover maxHeight + overflow pra medir tudo expandido
      const prevMax = measureRef.current.style.maxHeight;
      const prevOver = measureRef.current.style.overflowY;
      measureRef.current.style.maxHeight = 'none';
      measureRef.current.style.overflowY = 'visible';

      const children = measureRef.current.children;
      if (children.length === 0) {
        measureRef.current.style.maxHeight = prevMax;
        measureRef.current.style.overflowY = prevOver;
        return;
      }

      const fullHeight = measureRef.current.scrollHeight;
      const containerRect = measureRef.current.getBoundingClientRect();
      const containerTop = containerRect.top;
      const containerW = containerRect.width;

      // Linhas visíveis responsivas: tela pequena = 1, média = 2, grande = 3
      const maxLines = containerW < 300 ? 1 : containerW < 500 ? 2 : LEGEND_VISIBLE_LINES;

      // Agrupar filhos em linhas reais
      const lines: number[][] = [];
      const lineBottoms: number[] = [];
      let lastTop = -Infinity;
      for (let i = 0; i < children.length; i++) {
        const rect = children[i].getBoundingClientRect();
        const relTop = rect.top - containerTop;
        const relBottom = rect.bottom - containerTop;
        if (relTop > lastTop + 2) {
          lines.push([i]);
          lineBottoms.push(relBottom);
          lastTop = relTop;
        } else {
          lines[lines.length - 1].push(i);
          lineBottoms[lineBottoms.length - 1] = Math.max(lineBottoms[lineBottoms.length - 1], relBottom);
        }
      }

      // Calcular corte em linhas inteiras
      const totalLines = lines.length;
      const visibleLines = Math.min(maxLines, totalLines);
      const cutH = visibleLines > 0 ? lineBottoms[visibleLines - 1] + 2 : 60;

      // Contar itens visíveis = soma dos itens nas linhas visíveis
      let visibleItems = 0;
      for (let l = 0; l < visibleLines; l++) {
        visibleItems += lines[l].length;
      }

      // Restaurar estilos
      measureRef.current.style.maxHeight = prevMax;
      measureRef.current.style.overflowY = prevOver;

      setCollapsedH(cutH);
      const isOverflow = fullHeight > cutH + 4;
      setOverflows(isOverflow);
      setHiddenCount(isOverflow ? Math.max(0, (payload?.length || 0) - visibleItems) : 0);
    };
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [payload]);

  if (!payload?.length) return null;

  return (
    <div className="pt-3">
      <div
        ref={measureRef}
        className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-sm rounded-lg"
        style={{
          color: 'var(--color-text-secondary)',
          maxHeight: expanded ? `${LEGEND_MAX_H_EXPANDED}px` : `${collapsedH}px`,
          overflowY: expanded ? 'auto' : 'hidden',
          backgroundColor: expanded ? 'var(--color-surface)' : 'transparent',
          border: expanded ? '1px solid var(--color-border)' : '1px solid transparent',
          padding: expanded ? '10px 12px' : '0px 0px',
          transition: 'max-height 0.2s ease, background-color 0.2s ease, padding 0.2s ease, border-color 0.2s ease',
        }}
      >
        {payload.map((entry: any, i: number) => (
          <div key={i} className="flex items-center gap-1.5">
            <div className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: entry.color }} />
            <span>{entry.value}</span>
          </div>
        ))}
      </div>

      {overflows && (
        <div className="flex justify-center pt-1">
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-meta font-medium px-2.5 py-0.5 rounded-md transition-colors duration-150"
            style={{
              color: expanded ? 'var(--color-text-secondary)' : 'var(--color-primary-text)',
              backgroundColor: expanded ? 'transparent' : 'var(--color-primary-bg)',
            }}
          >
            {expanded ? 'Recolher' : `+${hiddenCount} ${hiddenCount === 1 ? 'item' : 'itens'}`}
          </button>
        </div>
      )}
    </div>
  );
}

function compactTick(v: number) {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}k`;
  return String(v);
}

// Bar border radius calculator for stacked bars
// @ts-ignore: reserved for future use
function _getBarRadius(serieKey: string, barKeys: string[], data: any, isVertical: boolean): string {
  const r = BORDER_RADIUS;
  if (barKeys.length <= 1) return `${r}px`;

  const vals = barKeys.map(k => ({ k, v: Number(data?.[k] ?? 0) })).filter(p => p.v !== 0);
  if (vals.length === 0) return `${r}px`;

  const isFirst = vals[0]?.k === serieKey;
  const isLast = vals[vals.length - 1]?.k === serieKey;

  if (isFirst && isLast) return `${r}px`;

  if (isVertical) {
    // Horizontal bars: left = zero side, right = tip
    if (isFirst) return `${r}px 0 0 ${r}px`;
    if (isLast) return `0 ${r}px ${r}px 0`;
  } else {
    // Vertical bars: bottom = zero, top = tip
    if (isFirst) return `0 0 ${r}px ${r}px`;
    if (isLast) return `${r}px ${r}px 0 0`;
  }
  return '0';
}

// ── ChartContainer ─────────────────────────────────────────────

interface ChartContainerProps {
  children: ReactNode;
  title?: ReactNode;
  subtitle?: string;
  className?: string;
  icon?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
}

export function ChartContainer({ children, title, subtitle, className = '', icon, action, footer }: ChartContainerProps) {
  return (
    <div
      className={`rounded-lg py-6 ${className}`}
      style={{ backgroundColor: 'var(--color-surface)', boxShadow: 'var(--shadow-card)' }}
    >
      {(title || subtitle || action) && (
        <div className="mb-6 px-6 flex items-start justify-between">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              {icon}
              {title && (typeof title === 'string'
                ? <h3 className="leading-none font-semibold" style={{ color: 'var(--color-text)' }}>{title}</h3>
                : title
              )}
            </div>
            {subtitle && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{subtitle}</p>}
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      <div className="px-6">
        {children}
      </div>
      {footer && (
        <div className="mt-4 px-6 flex flex-col items-start gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {footer}
        </div>
      )}
    </div>
  );
}

// ── ShadcnBarChart ─────────────────────────────────────────────

interface BarChartProps {
  data: any[];
  bars: { dataKey: string; color?: string; name?: string; showLabel?: boolean }[];
  xKey?: string;
  height?: number;
  formatter?: (v: number) => string;
  stacked?: boolean;
  activeIndex?: number | number[];
  onBarClick?: (item: any, index: number, event: any) => void;
  onRightClick?: (item: any, index: number, event: any) => void;
  layout?: 'horizontal' | 'vertical';
  /** Show value labels on all bars */
  showLabel?: boolean;
  /** Formatter specifically for labels (defaults to formatter or compactTick) */
  labelFormatter?: (v: number) => string;
}

export function ShadcnBarChart({
  data, bars, xKey = 'name', height: heightProp, formatter,
  stacked = false, activeIndex, onBarClick, onRightClick, layout = 'horizontal',
  showLabel = false, labelFormatter,
}: BarChartProps) {
  const isVertical = layout === 'vertical';
  const hoverRef = useRef<{ item: any; index: number } | null>(null);

  // Auto-calculate height for horizontal bars: ~50px per item, min 200
  const height = heightProp ?? (isVertical ? Math.max(200, data.length * 50) : 280);

  // ── Highlight logic ──
  const activeSet = activeIndex != null
    ? (Array.isArray(activeIndex) ? activeIndex : [activeIndex])
    : null;
  const isFiltered = activeSet != null && activeSet.length > 0;

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!onRightClick || !hoverRef.current) return;
    e.preventDefault();
    onRightClick(hoverRef.current.item, hoverRef.current.index, e.nativeEvent);
  }, [onRightClick]);

  // Radius for bar corners: vertical bars round the top, horizontal bars round the right tip
  const getBarRadius = (isLast: boolean): [number, number, number, number] => {
    if (stacked && !isLast) return [0, 0, 0, 0];
    if (isVertical) return [0, BORDER_RADIUS, BORDER_RADIUS, 0]; // round right tip
    return [BORDER_RADIUS, BORDER_RADIUS, 0, 0]; // round top
  };

  return (
    <div onContextMenu={handleContextMenu}>
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={isVertical ? 'vertical' : 'horizontal'}
        margin={isVertical ? { top: 5, right: 30, left: 10, bottom: 5 } : { top: 8, right: 12, left: 0, bottom: 0 }}
      >
        <CartesianGrid stroke="var(--color-border)" strokeOpacity={0.5} vertical={isVertical} horizontal={!isVertical} />
        <XAxis
          {...(isVertical
            ? { type: 'number' as const, tickFormatter: compactTick }
            : { dataKey: xKey }
          )}
          tickLine={false}
          tickMargin={10}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          {...(isVertical
            ? { type: 'category' as const, dataKey: xKey, width: 100 }
            : { tickFormatter: compactTick, width: 50 }
          )}
          tickLine={false}
          tickMargin={10}
          axisLine={false}
          fontSize={12}
        />
        <Tooltip content={<ChartTooltip formatter={formatter} />} cursor={false} />
        <Legend content={<ChartLegend />} />
        {(() => {
          // Compute uniform label color for stacked bars: if ANY bar is dark → all white, else all gray
          const barColors = bars.map((b, i) => b.color || CHART_SEQUENCE[i % CHART_SEQUENCE.length]);
          const stackedLabelColor = stacked && barColors.some(c => isDarkColor(c)) ? '#fff' : 'var(--color-label-muted)';
          return bars.map((bar, i) => {
            const color = barColors[i];
            const isLastInStack = stacked && i === bars.length - 1;
            return (
              <Bar
                key={bar.dataKey}
                dataKey={bar.dataKey}
                name={bar.name || bar.dataKey}
                fill={color}
                stackId={stacked ? 'stack' : undefined}
                radius={getBarRadius(!stacked || isLastInStack)}
                onClick={onBarClick ? (_payload: any, idx: number, e: any) => onBarClick(data[idx], idx, e) : undefined}
                onMouseEnter={onRightClick ? (_payload: any, idx: number) => { hoverRef.current = { item: data[idx], index: idx }; } : undefined}
                onMouseLeave={onRightClick ? () => { hoverRef.current = null; } : undefined}
                cursor={onBarClick || onRightClick ? 'pointer' : undefined}
                style={{ outline: 'none', stroke: 'none' }}
              >
                {isFiltered && data.map((_entry, idx) => (
                  <Cell
                    key={idx}
                    fillOpacity={activeSet!.includes(idx) ? 1 : 0.35}
                    style={{ outline: 'none', stroke: 'none', transition: 'fill-opacity 0.2s ease' }}
                  />
                ))}
                {(showLabel || bar.showLabel) && (
                  <LabelList
                    dataKey={bar.dataKey}
                    position={stacked ? 'center' : (isVertical ? 'right' : 'top')}
                    content={(props: any) => {
                      const { x, y, width, height: h, value } = props;
                      const fmt = labelFormatter || compactTick;
                      const label = fmt(value);
                      if (stacked) {
                        return (
                          <text x={x + width / 2} y={y + h / 2} textAnchor="middle" dominantBaseline="central"
                            style={{ fill: stackedLabelColor, fontSize: 10, fontWeight: 600 }}>{label}</text>
                        );
                      }
                      if (isVertical) {
                        return (
                          <text x={x + width + 6} y={y + h / 2} textAnchor="start" dominantBaseline="central"
                            style={{ fill: 'var(--color-label-muted)', fontSize: 11, fontWeight: 500 }}>{label}</text>
                        );
                      }
                      return (
                        <text x={x + width / 2} y={y - 6} textAnchor="middle"
                          style={{ fill: 'var(--color-label-muted)', fontSize: 11, fontWeight: 500 }}>{label}</text>
                      );
                    }}
                  />
                )}
              </Bar>
            );
          });
        })()}
      </BarChart>
    </ResponsiveContainer>
    </div>
  );
}

// ── ShadcnLineChart ────────────────────────────────────────────

interface LineChartProps {
  data: any[];
  lines: { dataKey: string; color?: string; name?: string; dashed?: boolean; showLabel?: boolean }[];
  xKey?: string;
  height?: number;
  formatter?: (v: number) => string;
  onDotClick?: (item: any, index: number, event: any) => void;
  onRightClick?: (item: any, index: number, event: any) => void;
  activeIndex?: number | number[];
  showLabel?: boolean;
  labelFormatter?: (v: number) => string;
}

export function ShadcnLineChart({ data, lines, xKey = 'name', height = 280, formatter, onDotClick, onRightClick, activeIndex, showLabel: globalShowLabel = false, labelFormatter }: LineChartProps) {
  const activeSet = activeIndex != null
    ? (Array.isArray(activeIndex) ? activeIndex : [activeIndex])
    : null;
  const isFiltered = activeSet != null && activeSet.length > 0;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart accessibilityLayer data={data} margin={{ top: globalShowLabel || lines.some(l => l.showLabel) ? 20 : 8, right: 12, left: 12, bottom: 0 }}>
        <CartesianGrid stroke="var(--color-border)" strokeOpacity={0.5} vertical={false} />
        <XAxis
          dataKey={xKey}
          {...AXIS_STYLE}
        />
        <YAxis
          {...AXIS_STYLE}
          tickFormatter={compactTick}
          width={50}
        />
        <Tooltip
          content={<ChartTooltip formatter={formatter} />}
          cursor={false}
        />
        <Legend content={<ChartLegend />} />
        {lines.map((line, i) => {
          const color = line.color || CHART_SEQUENCE[i % CHART_SEQUENCE.length];
          return (
            <Line
              key={line.dataKey}
              type="natural"
              dataKey={line.dataKey}
              name={line.name || line.dataKey}
              stroke={color}
              strokeWidth={2}
              strokeDasharray={line.dashed ? '6 3' : undefined}
              dot={(dotProps: any) => {
                const { cx, cy, index } = dotProps;
                const rcHandler = onRightClick ? (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); onRightClick(dotProps.payload, index, e.nativeEvent); } : undefined;
                if (isFiltered) {
                  const dimmed = !activeSet!.includes(index);
                  return (
                    <circle
                      key={`dot-${line.dataKey}-${index}`}
                      cx={cx} cy={cy} r={dimmed ? 2 : 4}
                      fill={color} stroke={dimmed ? 'none' : '#fff'} strokeWidth={dimmed ? 0 : 2}
                      opacity={dimmed ? 0.35 : 1}
                      style={{ transition: 'opacity 0.2s ease', cursor: (onDotClick || onRightClick) ? 'pointer' : 'default' }}
                      onClick={onDotClick ? (e) => { e.stopPropagation(); onDotClick(dotProps.payload, index, e); } : undefined}
                      onContextMenu={rcHandler}
                    />
                  );
                }
                // Not filtered: show small dots if clickable, hide otherwise
                if (onDotClick || onRightClick) {
                  return (
                    <circle
                      key={`dot-${line.dataKey}-${index}`}
                      cx={cx} cy={cy} r={3}
                      fill={color} stroke="#fff" strokeWidth={1.5}
                      style={{ cursor: 'pointer' }}
                      onClick={onDotClick ? (e) => { e.stopPropagation(); onDotClick(dotProps.payload, index, e); } : undefined}
                      onContextMenu={rcHandler}
                    />
                  );
                }
                return <circle key={`dot-${line.dataKey}-${index}`} cx={cx} cy={cy} r={0} fill="none" />;
              }}
              activeDot={(dotProps: any) => {
                const { cx, cy, index } = dotProps;
                const rcHandler = onRightClick ? (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); onRightClick(dotProps.payload, index, e.nativeEvent); } : undefined;
                return (
                  <circle
                    key={`adot-${line.dataKey}-${index}`}
                    cx={cx} cy={cy} r={6}
                    fill={color} stroke="#fff" strokeWidth={2}
                    style={{ cursor: (onDotClick || onRightClick) ? 'pointer' : 'default' }}
                    onClick={onDotClick ? (e) => { e.stopPropagation(); onDotClick(dotProps.payload, index, e); } : undefined}
                    onContextMenu={rcHandler}
                  />
                );
              }}
              isAnimationActive
              animationBegin={0}
              animationDuration={300}
              animationEasing="ease-out"
            >
              {(globalShowLabel || line.showLabel) && (
                <LabelList
                  dataKey={line.dataKey}
                  position="top"
                  offset={12}
                  className="fill-foreground"
                  fontSize={12}
                  formatter={labelFormatter || compactTick}
                />
              )}
            </Line>
          );
        })}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── ShadcnAreaChart ────────────────────────────────────────────

interface AreaChartProps {
  data: any[];
  areas: { dataKey: string; color?: string; name?: string; showLabel?: boolean }[];
  xKey?: string;
  height?: number;
  formatter?: (v: number) => string;
  onDotClick?: (item: any, index: number, event: any) => void;
  onRightClick?: (item: any, index: number, event: any) => void;
  activeIndex?: number | number[];
  stacked?: boolean;
  showLabel?: boolean;
  labelFormatter?: (v: number) => string;
}

export function ShadcnAreaChart({ data, areas, xKey = 'name', height = 280, formatter, onDotClick, onRightClick, activeIndex, stacked = false, showLabel: globalShowLabel = false, labelFormatter }: AreaChartProps) {
  const activeSet = activeIndex != null
    ? (Array.isArray(activeIndex) ? activeIndex : [activeIndex])
    : null;
  const isFiltered = activeSet != null && activeSet.length > 0;

  // Compute Y domain including negatives with 10% padding
  const allValues = data.flatMap(d => areas.map(a => Number(d[a.dataKey]) || 0));
  const dataMin = Math.min(0, ...allValues);
  const dataMax = Math.max(0, ...allValues);
  const yRange = dataMax - dataMin || 1;
  const yPadding = yRange * 0.1;
  const hasNegative = dataMin < 0;
  const yDomain: [number, number] = [
    hasNegative ? dataMin - yPadding : 0,
    dataMax + yPadding,
  ];

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart accessibilityLayer data={data} margin={{ top: globalShowLabel || areas.some(a => a.showLabel) ? 24 : 16, right: 12, left: 12, bottom: 0 }}>
        <defs>
          {areas.map((area, i) => {
            const color = area.color || CHART_SEQUENCE[i % CHART_SEQUENCE.length];
            return (
              <linearGradient key={area.dataKey} id={`gradient-${area.dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.8} />
                <stop offset="95%" stopColor={color} stopOpacity={0.1} />
              </linearGradient>
            );
          })}
        </defs>
        <CartesianGrid stroke="var(--color-border)" strokeOpacity={0.5} vertical={false} />
        <XAxis
          dataKey={xKey}
          {...AXIS_STYLE}
        />
        <YAxis
          {...AXIS_STYLE}
          tickFormatter={compactTick}
          width={50}
          domain={yDomain}
        />
        {hasNegative && (
          <ReferenceLine y={0} stroke="var(--color-border)" strokeOpacity={0.8} strokeDasharray="3 3" />
        )}
        <Tooltip
          content={<ChartTooltip formatter={formatter} />}
          cursor={false}
        />
        <Legend content={<ChartLegend />} />
        {areas.map((area, i) => {
          const color = area.color || CHART_SEQUENCE[i % CHART_SEQUENCE.length];
          return (
            <Area
              key={area.dataKey}
              type="natural"
              dataKey={area.dataKey}
              name={area.name || area.dataKey}
              stroke={color}
              strokeWidth={2}
              fill={`url(#gradient-${area.dataKey})`}
              fillOpacity={0.4}
              baseValue={hasNegative ? 0 : undefined}
              stackId={stacked ? 'stack' : undefined}
              dot={(dotProps: any) => {
                const { cx, cy, index } = dotProps;
                const rcHandler = onRightClick ? (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); onRightClick(dotProps.payload, index, e.nativeEvent); } : undefined;
                if (isFiltered) {
                  const dimmed = !activeSet!.includes(index);
                  return (
                    <circle
                      key={`area-dot-${area.dataKey}-${index}`}
                      cx={cx} cy={cy} r={dimmed ? 2 : 4}
                      fill={color} stroke={dimmed ? 'none' : '#fff'} strokeWidth={dimmed ? 0 : 2}
                      opacity={dimmed ? 0.35 : 1}
                      style={{ transition: 'opacity 0.2s ease', cursor: (onDotClick || onRightClick) ? 'pointer' : 'default' }}
                      onClick={onDotClick ? (e) => { e.stopPropagation(); onDotClick(dotProps.payload, index, e); } : undefined}
                      onContextMenu={rcHandler}
                    />
                  );
                }
                if (onDotClick || onRightClick) {
                  return (
                    <circle
                      key={`area-dot-${area.dataKey}-${index}`}
                      cx={cx} cy={cy} r={3}
                      fill={color} stroke="#fff" strokeWidth={1.5}
                      style={{ cursor: 'pointer' }}
                      onClick={onDotClick ? (e) => { e.stopPropagation(); onDotClick(dotProps.payload, index, e); } : undefined}
                      onContextMenu={rcHandler}
                    />
                  );
                }
                return <circle key={`area-dot-${area.dataKey}-${index}`} cx={cx} cy={cy} r={0} fill="none" />;
              }}
              activeDot={(dotProps: any) => {
                const { cx, cy, index } = dotProps;
                const rcHandler = onRightClick ? (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); onRightClick(dotProps.payload, index, e.nativeEvent); } : undefined;
                return (
                  <circle
                    key={`area-adot-${area.dataKey}-${index}`}
                    cx={cx} cy={cy} r={6}
                    fill={color} stroke="#fff" strokeWidth={2}
                    style={{ cursor: (onDotClick || onRightClick) ? 'pointer' : 'default' }}
                    onClick={onDotClick ? (e) => { e.stopPropagation(); onDotClick(dotProps.payload, index, e); } : undefined}
                    onContextMenu={rcHandler}
                  />
                );
              }}
              isAnimationActive
              animationBegin={0}
              animationDuration={300}
              animationEasing="ease-out"
            >
              {(globalShowLabel || area.showLabel) && (
                <LabelList
                  dataKey={area.dataKey}
                  position="top"
                  offset={12}
                  className="fill-foreground"
                  fontSize={12}
                  formatter={labelFormatter || compactTick}
                />
              )}
            </Area>
          );
        })}
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── ShadcnComposedChart ────────────────────────────────────────

interface ComposedChartProps {
  data: any[];
  bars?: { dataKey: string; color?: string; name?: string; showLabel?: boolean }[];
  lines?: { dataKey: string; color?: string; name?: string; dashed?: boolean; showLabel?: boolean }[];
  areas?: { dataKey: string; color?: string; name?: string }[];
  xKey?: string;
  height?: number;
  formatter?: (v: number) => string;
  /** Label formatter (compact by default) */
  labelFormatter?: (v: number) => string;
  stacked?: boolean;
  /** Show labels on all bars and lines */
  showLabel?: boolean;
  onBarClick?: (item: any, index: number, event: any) => void;
  onRightClick?: (item: any, index: number, event: any) => void;
  activeIndex?: number | number[];
}

export function ShadcnComposedChart({
  data, bars = [], lines = [], areas = [], xKey = 'name',
  height = 280, formatter, labelFormatter, stacked = false, showLabel: globalShowLabel = false,
  onBarClick, onRightClick, activeIndex,
}: ComposedChartProps) {
  const fmt = labelFormatter || compactTick;
  // Pre-compute colors for each series (areas → bars → lines order)
  let _cIdx = 0;
  const _next = () => CHART_SEQUENCE[_cIdx++ % CHART_SEQUENCE.length];
  const areaColors = areas.map(a => a.color || _next());
  const barColors = bars.map(b => b.color || _next());
  const lineColors = lines.map(l => l.color || _next());
  // Uniform stacked bar label color: any dark → all white, else gray
  const composedStackedLabelColor = stacked && barColors.some(c => isDarkColor(c)) ? '#fff' : 'var(--color-label-muted)';
  const hoverRef = useRef<{ item: any; index: number } | null>(null);

  const activeSet = activeIndex != null
    ? (Array.isArray(activeIndex) ? activeIndex : [activeIndex])
    : null;
  const isFiltered = activeSet != null && activeSet.length > 0;

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!onRightClick || !hoverRef.current) return;
    e.preventDefault();
    onRightClick(hoverRef.current.item, hoverRef.current.index, e.nativeEvent);
  }, [onRightClick]);

  return (
    <div onContextMenu={handleContextMenu}>
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart accessibilityLayer data={data} margin={{ top: globalShowLabel || bars.some(b => b.showLabel) || lines.some(l => l.showLabel) ? 24 : 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          {areas.map((area, aIdx) => {
            const color = areaColors[aIdx];
            return (
              <linearGradient key={`cg-${area.dataKey}`} id={`composed-gradient-${area.dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.8} />
                <stop offset="95%" stopColor={color} stopOpacity={0.1} />
              </linearGradient>
            );
          })}
        </defs>
        <CartesianGrid stroke="var(--color-border)" strokeOpacity={0.5} vertical={false} />
        <XAxis
          dataKey={xKey}
          {...AXIS_STYLE}
        />
        <YAxis
          {...AXIS_STYLE}
          tickFormatter={compactTick}
          width={50}
        />
        <Tooltip
          content={<ChartTooltip formatter={formatter} />}
          cursor={false}
        />
        <Legend content={<ChartLegend />} />
        {areas.map((area, aIdx) => {
          const color = areaColors[aIdx];
          return (
            <Area
              key={area.dataKey}
              type="natural"
              dataKey={area.dataKey}
              name={area.name || area.dataKey}
              stroke={color}
              strokeWidth={2}
              fill={`url(#composed-gradient-${area.dataKey})`}
              fillOpacity={0.4}
              dot={isFiltered ? ((dotProps: any) => {
                const { cx, cy, index } = dotProps;
                const dimmed = !activeSet!.includes(index);
                return (
                  <circle
                    key={`ca-dot-${area.dataKey}-${index}`}
                    cx={cx} cy={cy} r={dimmed ? 2 : 4}
                    fill={color} stroke={dimmed ? 'none' : '#fff'} strokeWidth={dimmed ? 0 : 2}
                    opacity={dimmed ? 0.35 : 1}
                    style={{ transition: 'opacity 0.2s ease' }}
                  />
                );
              }) : false}
              isAnimationActive
              animationBegin={0}
              animationDuration={300}
              animationEasing="ease-out"
            />
          );
        })}
        {bars.map((bar, barIdx) => {
          const color = barColors[barIdx];
          const isLastInStack = stacked && barIdx === bars.length - 1;
          return (
            <Bar
              key={bar.dataKey}
              dataKey={bar.dataKey}
              name={bar.name || bar.dataKey}
              fill={color}
              stackId={stacked ? 'stack' : undefined}
              radius={(!stacked || isLastInStack) ? [BORDER_RADIUS, BORDER_RADIUS, 0, 0] : [0, 0, 0, 0]}
              onClick={onBarClick ? (_payload: any, idx: number, e: any) => onBarClick(data[idx], idx, e) : undefined}
              onMouseEnter={onRightClick ? (_payload: any, idx: number) => { hoverRef.current = { item: data[idx], index: idx }; } : undefined}
              onMouseLeave={onRightClick ? () => { hoverRef.current = null; } : undefined}
              cursor={onBarClick || onRightClick ? 'pointer' : undefined}
              style={{ outline: 'none', stroke: 'none' }}
              isAnimationActive
              animationDuration={300}
              animationEasing="ease-out"
            >
              {isFiltered && data.map((_entry, idx) => (
                <Cell
                  key={idx}
                  fillOpacity={activeSet!.includes(idx) ? 1 : 0.35}
                  style={{ outline: 'none', stroke: 'none', transition: 'fill-opacity 0.2s ease' }}
                />
              ))}
              {(globalShowLabel || bar.showLabel) && (
                <LabelList
                  dataKey={bar.dataKey}
                  position="center"
                  content={(props: any) => {
                    const { x, y, width, height: h, value } = props;
                    const label = fmt(value);
                    return (
                      <text x={x + width / 2} y={y + h / 2} textAnchor="middle" dominantBaseline="central"
                        style={{ fill: composedStackedLabelColor, fontSize: 10, fontWeight: 600 }}>{label}</text>
                    );
                  }}
                />
              )}
            </Bar>
          );
        })}
        {lines.map((line, lIdx) => {
          const color = lineColors[lIdx];
          const lineShowLabel = globalShowLabel || line.showLabel;
          return (
            <Line
              key={line.dataKey}
              type="natural"
              dataKey={line.dataKey}
              name={line.name || line.dataKey}
              stroke={color}
              strokeWidth={2}
              strokeDasharray={line.dashed ? '6 3' : undefined}
              dot={isFiltered ? ((dotProps: any) => {
                const { cx, cy, index } = dotProps;
                const dimmed = !activeSet!.includes(index);
                return (
                  <circle
                    key={`cl-dot-${line.dataKey}-${index}`}
                    cx={cx} cy={cy} r={dimmed ? 2 : 4}
                    fill={color} stroke={dimmed ? 'none' : '#fff'} strokeWidth={dimmed ? 0 : 2}
                    opacity={dimmed ? 0.35 : 1}
                    style={{ transition: 'opacity 0.2s ease' }}
                  />
                );
              }) : false}
              activeDot={(dotProps: any) => {
                const { cx, cy, index } = dotProps;
                return (
                  <circle
                    key={`cl-adot-${line.dataKey}-${index}`}
                    cx={cx} cy={cy} r={6}
                    fill={color} stroke="#fff" strokeWidth={2}
                    style={{ transition: 'opacity 0.2s ease' }}
                  />
                );
              }}
              isAnimationActive
              animationBegin={0}
              animationDuration={300}
              animationEasing="ease-in-out"
            >
              {lineShowLabel && (
                <LabelList
                  dataKey={line.dataKey}
                  position="top"
                  offset={12}
                  className="fill-foreground"
                  fontSize={12}
                  formatter={fmt}
                />
              )}
            </Line>
          );
        })}
      </ComposedChart>
    </ResponsiveContainer>
    </div>
  );
}

// ── ShadcnPieChart ─────────────────────────────────────────────

interface PieDataItem {
  name: string;
  value: number;
  color?: string;
}

interface PieChartProps {
  data: PieDataItem[];
  height?: number;
  formatter?: (v: number) => string;
  donut?: boolean;
  onSliceClick?: (item: PieDataItem, index: number, event: any) => void;
  onRightClick?: (item: PieDataItem, index: number, event: any) => void;
  interactive?: boolean;
  activeIndex?: number | number[];
  /** Show labels outside slices (name + value/percent) */
  showLabel?: boolean;
  /** Label content: 'value' = formatted value, 'percent' = percentage, 'name' = category name, 'name-percent' = both */
  labelType?: 'value' | 'percent' | 'name' | 'name-percent';
}

export function ShadcnPieChart({
  data, height: heightProp = 280, formatter, donut = true,
  onSliceClick, onRightClick, interactive = true, activeIndex: activeIndexProp,
  showLabel = false, labelType = 'name-percent',
}: PieChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const hoverRef = useRef<{ item: any; index: number } | null>(null);
  const pieWrapperRef = useRef<HTMLDivElement>(null);
  const [containerW, setContainerW] = useState(0);

  useEffect(() => {
    const el = pieWrapperRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width || 0;
      setContainerW(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Altura responsiva: tela grande = heightProp, tela pequena = reduz proporcionalmente (min 200)
  const height = containerW > 0 ? Math.min(heightProp, Math.max(200, Math.round(containerW * 0.85))) : heightProp;

  // Compute which indices are "active" (highlighted)
  const activeSet = activeIndexProp != null
    ? (Array.isArray(activeIndexProp) ? activeIndexProp : [activeIndexProp])
    : null;
  const isFiltered = activeSet != null && activeSet.length > 0;

  // Total for labels
  const totalForLabel = data.reduce((s, d) => s + d.value, 0);


  // Custom activeShape — renders identical to normal slice, no stroke
  const pieActiveShape = (props: any) => (
    <Sector
      cx={props.cx}
      cy={props.cy}
      innerRadius={props.innerRadius}
      outerRadius={props.outerRadius + 4}
      startAngle={props.startAngle}
      endAngle={props.endAngle}
      fill={props.fill}
      fillOpacity={props.fillOpacity ?? 1}
      stroke="none"
      strokeWidth={0}
      style={{ outline: 'none' }}
    />
  );

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!onRightClick || !hoverRef.current) return;
    e.preventDefault();
    onRightClick(hoverRef.current.item, hoverRef.current.index, e.nativeEvent);
  }, [onRightClick]);

  return (
    <>
      {/* CSS override: kill any stroke/outline that Recharts injects on active/focus */}
      <style>{`
        .recharts-pie-sector path,
        .recharts-pie-sector .recharts-active-shape path,
        .recharts-pie path {
          stroke: none !important;
          stroke-width: 0 !important;
          outline: none !important;
        }
        .recharts-pie-sector,
        .recharts-pie-sector:focus,
        .recharts-pie-sector:active,
        .recharts-pie-sector g {
          outline: none !important;
        }
      `}</style>
      <div ref={pieWrapperRef} onContextMenu={handleContextMenu} onMouseLeave={() => { setHoverIndex(null); hoverRef.current = null; }}>
      <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={donut ? '50%' : 0}
          outerRadius={showLabel ? '80%' : '92%'}
          dataKey="value"
          nameKey="name"
          stroke="none"
          strokeWidth={0}
          activeIndex={hoverIndex != null ? hoverIndex : undefined}
          activeShape={pieActiveShape}
          inactiveShape={{ stroke: 'none', strokeWidth: 0 }}
          onMouseEnter={interactive ? (_: any, index: number) => { setHoverIndex(index); hoverRef.current = { item: data[index], index }; } : undefined}
          onMouseLeave={interactive ? () => { setHoverIndex(null); hoverRef.current = null; } : undefined}
          onClick={onSliceClick ? (_data: any, index: number, e: any) => onSliceClick(data[index], index, e) : undefined}
          cursor={onSliceClick || onRightClick ? 'pointer' : undefined}
          isAnimationActive
          animationDuration={500}
          label={showLabel ? (props: any) => {
            const RADIAN = Math.PI / 180;
            const { cx, cy, midAngle, outerRadius: or, index, value, name } = props;
            const sliceColor = data[index]?.color || CHART_SEQUENCE[index % CHART_SEQUENCE.length];
            // Responsive: cx = metade da largura do container
            const containerW = cx * 2;
            const isSmall = containerW < 300;
            const isTiny = containerW < 220;
            const labelRadius = or + (isSmall ? 12 : 20);
            const fs = isTiny ? 9 : isSmall ? 10 : 12;
            const x = cx + labelRadius * Math.cos(-midAngle * RADIAN);
            const y = cy + labelRadius * Math.sin(-midAngle * RADIAN);
            const isRight = x > cx;
            // Espaço disponível até a borda do SVG (px)
            const availablePx = isRight ? (containerW - x - 4) : (x - 4);
            // ~0.6em por caractere (aprox para font 600)
            const maxChars = Math.max(4, Math.floor(availablePx / (fs * 0.6)));
            const pctNum = totalForLabel > 0 ? (value / totalForLabel) * 100 : 0;
            // Só mostra label para fatias >= 3%
            if (pctNum < 3) return null;
            const pct = pctNum.toFixed(1) + '%';
            const fmtVal = formatter ? formatter(value) : value?.toLocaleString('pt-BR');
            let text = '';
            if (labelType === 'name') text = name;
            else if (labelType === 'value') text = fmtVal;
            else if (labelType === 'percent') text = pct;
            else if (isTiny) text = pct;
            else text = `${name} (${pct})`;
            // Truncar com ... se não cabe
            if (text.length > maxChars) {
              text = text.slice(0, maxChars - 1).trimEnd() + '\u2026';
            }
            return (
              <text
                x={x}
                y={y}
                textAnchor={isRight ? 'start' : 'end'}
                dominantBaseline="central"
                style={{ fill: sliceColor, fontSize: fs, fontWeight: 600 }}
              >
                {text}
              </text>
            );
          } : false}
          labelLine={false}
        >
          {data.map((entry, i) => {
            const color = entry.color || CHART_SEQUENCE[i % CHART_SEQUENCE.length];
            const dimmed = isFiltered && !activeSet!.includes(i);
            return (
              <Cell
                key={i}
                fill={color}
                stroke="none"
                strokeWidth={0}
                fillOpacity={dimmed ? 0.35 : 1}
                style={{ outline: 'none' }}
              />
            );
          })}
        </Pie>
        <Tooltip
          content={<ChartTooltip formatter={formatter} hideLabel />}
          cursor={false}
          isAnimationActive={false}
          active={hoverIndex != null}
        />
        <Legend content={<ChartLegend />} />
      </PieChart>
    </ResponsiveContainer>
    </div>
    </>
  );
}

// ── ShadcnDataTable ────────────────────────────────────────────

interface ColumnDef {
  key: string;
  label: string;
  align?: 'left' | 'right' | 'center';
  formatter?: (v: any) => string;
  width?: string;
}

interface DataTableProps {
  data: any[];
  columns: ColumnDef[];
  /** Indices ativos (do useHighlight) — linhas fora ficam dimmed */
  activeIndex?: number | number[];
  /** Click na linha — usar hl.handler */
  onRowClick?: (item: any, index: number, event: any) => void;
  /** Right-click na linha — usar drill.handleRightClick */
  onRowRightClick?: (item: any, index: number, event: any) => void;
  /** Linha selecionada fica com bg colorido */
  highlightColor?: string;
  /** Mostrar indice da linha */
  showIndex?: boolean;
  /** Max height com scroll */
  maxHeight?: number;
  /** Compact mode (py-1.5 em vez de py-2.5) */
  compact?: boolean;
}

export function ShadcnDataTable({
  data, columns, activeIndex, onRowClick, onRowRightClick,
  highlightColor, showIndex = false, maxHeight, compact = false,
}: DataTableProps) {
  const activeSet = activeIndex != null
    ? (Array.isArray(activeIndex) ? activeIndex : [activeIndex])
    : null;
  const isFiltered = activeSet != null && activeSet.length > 0;
  const py = compact ? 'py-1.5' : 'py-2.5';

  return (
    <div
      className="overflow-auto rounded-lg border"
      style={{
        borderColor: 'var(--color-border)',
        maxHeight: maxHeight ?? undefined,
      }}
    >
      <table className="w-full text-sm">
        <thead>
          <tr style={{ backgroundColor: 'var(--color-bg)' }}>
            {showIndex && (
              <th className={`${py} px-4 text-left text-meta font-medium`} style={{ color: 'var(--color-text-secondary)', width: '40px' }}>#</th>
            )}
            {columns.map(col => (
              <th
                key={col.key}
                className={`${py} px-4 text-meta font-medium`}
                style={{
                  color: 'var(--color-text-secondary)',
                  textAlign: col.align || 'left',
                  width: col.width,
                }}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, idx) => {
            const isActive = !isFiltered || activeSet!.includes(idx);
            const isSelected = isFiltered && activeSet!.includes(idx);
            return (
              <tr
                key={idx}
                className="border-t transition-all duration-150"
                style={{
                  borderColor: 'var(--color-border)',
                  opacity: isActive ? 1 : 0.35,
                  backgroundColor: isSelected
                    ? (highlightColor || 'color-mix(in srgb, var(--chart-1) 8%, transparent)')
                    : 'transparent',
                  cursor: (onRowClick || onRowRightClick) ? 'pointer' : 'default',
                }}
                onClick={onRowClick ? (e) => onRowClick(row, idx, e.nativeEvent) : undefined}
                onContextMenu={onRowRightClick ? (e) => {
                  e.preventDefault();
                  onRowRightClick(row, idx, e.nativeEvent);
                } : undefined}
              >
                {showIndex && (
                  <td className={`${py} px-4 tabular-nums`} style={{ color: 'var(--color-label-muted)' }}>{idx + 1}</td>
                )}
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={`${py} px-4`}
                    style={{
                      color: isSelected ? 'var(--color-text)' : 'var(--color-text)',
                      textAlign: col.align || 'left',
                      fontWeight: isSelected ? 500 : 400,
                      fontVariantNumeric: col.align === 'right' ? 'tabular-nums' : undefined,
                    }}
                  >
                    {col.formatter ? col.formatter(row[col.key]) : (row[col.key] ?? '—')}
                  </td>
                ))}
              </tr>
            );
          })}
          {data.length === 0 && (
            <tr>
              <td
                colSpan={columns.length + (showIndex ? 1 : 0)}
                className="py-6 text-center text-sm"
                style={{ color: 'var(--color-label-muted)' }}
              >
                Nenhum dado disponivel
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Drill-Down Components ───────────────────────────────────────

// Local types for drill components (mirrors useDrill.ts — no cross-file type imports due to verbatimModuleSyntax)
interface DrillDimensionLocal {
  key: string;
  label: string;
  description?: string;
}

interface DrillLevelLocal {
  label: string;
  [key: string]: any;
}

// ── DrillBreadcrumb ─────────────────────────────────────────────

interface DrillBreadcrumbProps {
  stack: DrillLevelLocal[];
  rootLabel?: string;
  onNavigate: (index: number) => void;
  className?: string;
}

export function DrillBreadcrumb({ stack, rootLabel = 'Visão Geral', onNavigate, className = '' }: DrillBreadcrumbProps) {
  if (stack.length === 0) return null;
  // Breadcrumb shows: Visão Geral › Level1 › Level2 › ... › Current
  // Each intermediate level is clickable to navigate back

  const chevron = (
    <svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={{ color: 'var(--color-label-muted)', flexShrink: 0 }}>
      <path d="m9 18 6-6-6-6" />
    </svg>
  );

  return (
    <nav className={`flex items-center gap-1 ${className || 'text-meta mb-3'}`}>
      <button
        onClick={() => onNavigate(-1)}
        className="hover:underline transition-colors font-medium px-1.5 py-0.5 rounded"
        style={{ color: 'var(--color-breadcrumb)' }}
      >
        {rootLabel}
      </button>
      {stack.map((level, i) => {
        const isLast = i === stack.length - 1;
        return (
          <span key={i} className="flex items-center gap-1">
            {chevron}
            {isLast ? (
              <span className="font-semibold px-1.5 py-0.5" style={{ color: 'var(--color-drill-text)' }}>
                {level.label}
              </span>
            ) : (
              <button
                onClick={() => onNavigate(i)}
                className="hover:underline transition-colors font-medium px-1.5 py-0.5 rounded"
                style={{ color: 'var(--color-breadcrumb)' }}
              >
                {level.label}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}

// ── DrillContextMenu ────────────────────────────────────────────

interface DrillContextMenuProps {
  x: number;
  y: number;
  dimensions: DrillDimensionLocal[];
  onSelect: (dimensionKey: string) => void;
  onClose: () => void;
}

export function DrillContextMenu({ x, y, dimensions, onSelect, onClose }: DrillContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x, y });

  // Adjust position to avoid viewport overflow
  useEffect(() => {
    if (menuRef.current) {
      const rect = menuRef.current.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      setPos({
        x: x + rect.width > vw ? Math.max(8, vw - rect.width - 8) : x,
        y: y + rect.height > vh ? Math.max(8, vh - rect.height - 8) : y,
      });
    }
  }, [x, y]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <>
      {/* Invisible backdrop to capture click-outside */}
      <div className="fixed inset-0 z-40" onClick={onClose} />

      {/* Menu */}
      <div
        ref={menuRef}
        className="fixed z-50 min-w-[180px] rounded-lg border shadow-lg py-1 animate-scaleIn"
        style={{
          left: pos.x,
          top: pos.y,
          backgroundColor: 'var(--color-surface, #fff)',
          borderColor: 'var(--color-border, #e2e8f0)',
        }}
      >
        <div className="px-3 py-1.5 text-meta font-medium uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>
          Detalhar por
        </div>
        <div className="border-t mx-1" style={{ borderColor: 'var(--color-border, #e2e8f0)' }} />

        {dimensions.length === 0 ? (
          <div className="px-3 py-2.5 text-meta" style={{ color: 'var(--color-label-muted)' }}>
            Nenhuma dimensão disponível
          </div>
        ) : (
          dimensions.map((dim) => (
            <button
              key={dim.key}
              onClick={() => onSelect(dim.key)}
              className="w-full text-left px-3 py-2 text-sm transition-colors hover:bg-[var(--color-drill-hover)]"
              style={{ color: 'var(--color-drill-text)' }}
            >
              <div className="font-medium">{dim.label}</div>
              {dim.description && (
                <div className="text-meta mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>{dim.description}</div>
              )}
            </button>
          ))
        )}
      </div>
    </>
  );
}

