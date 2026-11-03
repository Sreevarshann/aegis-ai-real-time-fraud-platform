// Chart primitives. Palette validated with the dataviz validator against the dark surface (#0a1020):
// categorical order blue -> teal -> violet. Risk bands use the reserved status colours with labels.
import type { ReactNode } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

export const SERIES = ["#4c8dff", "#0fa595", "#9b6cf6"] as const;
const AXIS = { stroke: "#62708f", fontSize: 11, tickLine: false, axisLine: false } as const;
const GRID = <CartesianGrid stroke="#1e2a44" strokeDasharray="3 3" vertical={false} />;

interface TipProps { active?: boolean; payload?: { name?: string; value?: number | string; color?: string; payload?: Record<string, unknown> }[]; label?: string | number }

function ChartTooltip({ active, payload, label, labelFormatter, valueFormatter }: TipProps & {
  labelFormatter?: (l: string | number) => ReactNode; valueFormatter?: (v: number | string) => ReactNode;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-ink-850/95 px-3 py-2 text-[12px] shadow-xl backdrop-blur">
      {label != null && <div className="mb-1 text-mist-500">{labelFormatter ? labelFormatter(label) : label}</div>}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />
          <span className="text-mist-300">{p.name}</span>
          <span className="num ml-auto pl-4 text-mist-100">{valueFormatter && p.value != null ? valueFormatter(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function VolumeChart({ data, height = 220, color = SERIES[0], dataKey = "transactions", name = "Transactions" }: {
  data: Record<string, unknown>[]; height?: number; color?: string; dataKey?: string; name?: string;
}) {
  const fmt = (v: string | number) => new Date(v).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`g-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {GRID}
        <XAxis dataKey="bucket" tickFormatter={fmt} minTickGap={40} {...AXIS} />
        <YAxis allowDecimals={false} width={48} {...AXIS} />
        <Tooltip cursor={{ stroke: "#4c8dff", strokeOpacity: 0.3 }} content={<ChartTooltip labelFormatter={(l) => fmt(l)} />} />
        <Area type="monotone" dataKey={dataKey} name={name} stroke={color} strokeWidth={2} fill={`url(#g-${dataKey})`}
          activeDot={{ r: 4, stroke: "#0a1020", strokeWidth: 2 }} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function BarsChart({ data, x, y, name, height = 220, colors, color = SERIES[0], valueFormatter, layout = "horizontal" }: {
  data: Record<string, unknown>[]; x: string; y: string; name: string; height?: number; colors?: string[];
  color?: string; valueFormatter?: (v: number | string) => ReactNode; layout?: "horizontal" | "vertical";
}) {
  const vertical = layout === "vertical";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={vertical ? "vertical" : "horizontal"} margin={{ top: 8, right: 12, left: vertical ? 8 : 0, bottom: 0 }} barCategoryGap="22%">
        <CartesianGrid stroke="#1e2a44" strokeDasharray="3 3" vertical={vertical} horizontal={!vertical} />
        {vertical ? (
          <>
            <XAxis type="number" {...AXIS} />
            <YAxis type="category" dataKey={x} width={170} {...AXIS} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...AXIS} interval={0} />
            <YAxis width={52} {...AXIS} />
          </>
        )}
        <Tooltip cursor={{ fill: "rgba(76,141,255,0.06)" }} content={<ChartTooltip valueFormatter={valueFormatter} />} />
        <Bar dataKey={y} name={name} fill={color} radius={vertical ? [0, 4, 4, 0] : [4, 4, 0, 0]} isAnimationActive={false}>
          {colors && data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
        </Bar>
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
        {GRID}
        <XAxis dataKey={x} tickFormatter={xFormatter} minTickGap={30} {...AXIS} />
        <YAxis width={52} {...AXIS} />
        <Tooltip cursor={{ stroke: "#4c8dff", strokeOpacity: 0.3 }}
          content={<ChartTooltip labelFormatter={xFormatter ? (l) => xFormatter(l) : undefined} valueFormatter={valueFormatter} />} />
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={SERIES[i % SERIES.length]} strokeWidth={2}
            dot={false} activeDot={{ r: 4, stroke: "#0a1020", strokeWidth: 2 }} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-mist-300">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: i.color }} />{i.label}
        </span>
      ))}
    </div>
  );
}
