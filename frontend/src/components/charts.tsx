// Chart primitives. Categorical palette (blue -> teal -> violet) validated with the dataviz validator against
// the white card surface (#ffffff): lightness band, chroma, CVD and normal-vision separation, 3:1 contrast.
// Risk bands use the reserved status colours and are always paired with text labels.
import type { ReactNode } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

export const SERIES = ["#2563eb", "#0d9488", "#7c3aed"] as const;
const AXIS = { stroke: "#94a3b8", fontSize: 11, tickLine: false, axisLine: false, tick: { fill: "#64748b" } } as const;
const GRID_STROKE = "#eef1f6";

interface TipProps { active?: boolean; payload?: { name?: string; value?: number | string; color?: string; payload?: Record<string, unknown> }[]; label?: string | number }

export function ChartTooltip({ active, payload, label, labelFormatter, valueFormatter }: TipProps & {
  labelFormatter?: (l: string | number) => ReactNode; valueFormatter?: (v: number | string) => ReactNode;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 text-[12px] shadow-lift">
      {label != null && <div className="mb-1 font-medium text-fg-3">{labelFormatter ? labelFormatter(label) : label}</div>}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-fg-2">{p.name}</span>
          <span className="num ml-auto pl-4 font-semibold text-fg">{valueFormatter && p.value != null ? valueFormatter(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

const timeFmt = (v: string | number) => new Date(v).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" });

export function VolumeChart({ data, height = 220, color = SERIES[0], dataKey = "transactions", name = "Transactions" }: {
  data: Record<string, unknown>[]; height?: number; color?: string; dataKey?: string; name?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`g-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID_STROKE} vertical={false} />
        <XAxis dataKey="bucket" tickFormatter={timeFmt} minTickGap={40} {...AXIS} />
        <YAxis allowDecimals={false} width={48} {...AXIS} />
        <Tooltip cursor={{ stroke: color, strokeOpacity: 0.25 }} content={<ChartTooltip labelFormatter={(l) => timeFmt(l)} />} />
        <Area type="monotone" dataKey={dataKey} name={name} stroke={color} strokeWidth={2.25} fill={`url(#g-${dataKey})`}
          activeDot={{ r: 4.5, stroke: "#ffffff", strokeWidth: 2 }} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** White bars on the brand gradient card (overview hero). */
export function HeroBars({ data, dataKey, name, height = 190 }: {
  data: Record<string, unknown>[]; dataKey: string; name: string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -8, bottom: 0 }} barCategoryGap="28%">
        <CartesianGrid stroke="rgba(255,255,255,0.14)" strokeDasharray="4 4" vertical={false} />
        <XAxis dataKey="bucket" tickFormatter={timeFmt} minTickGap={36} stroke="rgba(255,255,255,0.7)" fontSize={11}
          tickLine={false} axisLine={false} tick={{ fill: "rgba(255,255,255,0.8)" }} />
        <YAxis allowDecimals={false} width={40} fontSize={11} tickLine={false} axisLine={false} tick={{ fill: "rgba(255,255,255,0.8)" }} />
        <Tooltip cursor={{ fill: "rgba(255,255,255,0.12)" }} content={<ChartTooltip labelFormatter={(l) => timeFmt(l)} />} />
        <Bar dataKey={dataKey} name={name} fill="#ffffff" radius={[4, 4, 4, 4]} maxBarSize={10} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function BarsChart({ data, x, y, name, height = 220, colors, color = SERIES[0], valueFormatter, layout = "horizontal", xFormatter, categoryWidth = 170 }: {
  data: Record<string, unknown>[]; x: string; y: string; name: string; height?: number; colors?: string[];
  color?: string; valueFormatter?: (v: number | string) => ReactNode; layout?: "horizontal" | "vertical";
  xFormatter?: (v: string | number) => string; categoryWidth?: number;
}) {
  const vertical = layout === "vertical";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={vertical ? "vertical" : "horizontal"} margin={{ top: 8, right: 12, left: vertical ? 8 : 0, bottom: 0 }} barCategoryGap="24%">
        <CartesianGrid stroke={GRID_STROKE} vertical={vertical} horizontal={!vertical} />
        {vertical ? (
          <>
            <XAxis type="number" {...AXIS} />
            <YAxis type="category" dataKey={x} width={categoryWidth} {...AXIS} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...AXIS} tickFormatter={xFormatter} minTickGap={xFormatter ? 24 : 0} interval={xFormatter ? "preserveStartEnd" : 0} />
            <YAxis width={52} allowDecimals={false} {...AXIS} />
          </>
        )}
        <Tooltip cursor={{ fill: "rgba(37,99,235,0.05)" }}
          content={<ChartTooltip valueFormatter={valueFormatter} labelFormatter={xFormatter ? (l) => xFormatter(l) : undefined} />} />
        <Bar dataKey={y} name={name} fill={color} radius={vertical ? [0, 6, 6, 0] : [6, 6, 0, 0]} maxBarSize={vertical ? 18 : 36} isAnimationActive={false}>
          {colors && data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({ data, x, series, height = 230, yFormatter, valueFormatter }: {
  data: Record<string, unknown>[]; x: string; series: { key: string; name: string }[]; height?: number;
  yFormatter?: (v: number) => string; valueFormatter?: (v: number | string) => ReactNode;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 12, right: 8, left: 0, bottom: 0 }} barGap={2} barCategoryGap="22%">
        <CartesianGrid stroke={GRID_STROKE} vertical={false} />
        <XAxis dataKey={x} {...AXIS} />
        <YAxis width={48} tickFormatter={yFormatter} {...AXIS} />
        <Tooltip cursor={{ fill: "rgba(37,99,235,0.05)" }} content={<ChartTooltip valueFormatter={valueFormatter} />} />
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.name} fill={SERIES[i % SERIES.length]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function LinesChart({ data, x, series, height = 220, xFormatter, valueFormatter }: {
  data: Record<string, unknown>[]; x: string; series: { key: string; name: string }[]; height?: number;
  xFormatter?: (v: string | number) => string; valueFormatter?: (v: number | string) => ReactNode;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={GRID_STROKE} vertical={false} />
        <XAxis dataKey={x} tickFormatter={xFormatter} minTickGap={30} {...AXIS} />
        <YAxis width={52} {...AXIS} />
        <Tooltip cursor={{ stroke: SERIES[0], strokeOpacity: 0.25 }}
          content={<ChartTooltip labelFormatter={xFormatter ? (l) => xFormatter(l) : undefined} valueFormatter={valueFormatter} />} />
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={SERIES[i % SERIES.length]} strokeWidth={2.25}
            dot={false} activeDot={{ r: 4.5, stroke: "#ffffff", strokeWidth: 2 }} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-fg-2">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: i.color }} />{i.label}
        </span>
      ))}
    </div>
  );
}
