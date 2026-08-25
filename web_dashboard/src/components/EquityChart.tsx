"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityPoint } from "../lib/types";

type Props = {
  data: EquityPoint[];
  height?: number;
  compact?: boolean;
};

export function EquityChart({ data, height = 280, compact = false }: Props) {
  const series = (data || []).map((d) => ({
    t: d.timestamp?.slice(0, 16) ?? "",
    equity: Number(d.equity),
  }));
  if (!series.length) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-zinc-500">
        No equity curve yet
      </div>
    );
  }
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <AreaChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#34d399" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
            </linearGradient>
          </defs>
          {!compact && <CartesianGrid stroke="#27272a" strokeDasharray="3 3" />}
          {!compact && (
            <XAxis dataKey="t" tick={{ fill: "#71717a", fontSize: 11 }} hide={compact} />
          )}
          {!compact && (
            <YAxis
              tick={{ fill: "#71717a", fontSize: 11 }}
              domain={["auto", "auto"]}
              width={64}
            />
          )}
          {!compact && (
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: 8,
              }}
            />
          )}
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#34d399"
            fill="url(#eqFill)"
            strokeWidth={2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
