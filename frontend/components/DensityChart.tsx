"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Point = { x: number; density: number };

export function DensityChart({
  data,
  marketLine,
  mean,
}: {
  data: Point[];
  marketLine: number | null;
  mean: number | null;
}) {
  if (!data.length) {
    return (
      <p className="text-sm text-[var(--muted)]">No density available for this forecast.</p>
    );
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
          <XAxis
            dataKey="x"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(v: number) => v.toFixed(0)}
            stroke="#78716c"
            fontSize={12}
          />
          <YAxis hide />
          <Tooltip
            formatter={(value: number | string) =>
              typeof value === "number" ? value.toFixed(4) : value
            }
            labelFormatter={(label) => `stat ≈ ${Number(label).toFixed(1)}`}
          />
          <Area
            type="monotone"
            dataKey="density"
            stroke="#1c1917"
            fill="#0f766e"
            fillOpacity={0.25}
            isAnimationActive={false}
          />
          {mean !== null ? (
            <ReferenceLine
              x={mean}
              stroke="#0f766e"
              strokeDasharray="4 4"
              label={{ value: "mean", position: "insideTopLeft", fill: "#0f766e", fontSize: 11 }}
            />
          ) : null}
          {marketLine !== null ? (
            <ReferenceLine
              x={marketLine}
              stroke="#b45309"
              label={{ value: "line", position: "insideTopRight", fill: "#b45309", fontSize: 11 }}
            />
          ) : null}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
