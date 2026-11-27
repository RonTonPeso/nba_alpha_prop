"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Bin = {
  lower: number;
  upper: number;
  count: number;
  mean_predicted: number | null;
  realized_rate: number | null;
};

export function CalibrationChart({ bins }: { bins: Bin[] }) {
  const data = bins
    .filter((b) => b.mean_predicted !== null && b.realized_rate !== null)
    .map((b) => ({
      predicted: b.mean_predicted as number,
      realized: b.realized_rate as number,
      perfect: b.mean_predicted as number,
      count: b.count,
    }));

  if (!data.length) {
    return (
      <p className="text-sm text-[var(--muted)]">No calibration bins with counts.</p>
    );
  }

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
          <XAxis
            dataKey="predicted"
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => v.toFixed(1)}
            stroke="#78716c"
            fontSize={12}
          />
          <YAxis
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => v.toFixed(1)}
            stroke="#78716c"
            fontSize={12}
          />
          <Tooltip
            formatter={(value: number | string) =>
              typeof value === "number" ? value.toFixed(3) : value
            }
          />
          <Line
            type="linear"
            dataKey="perfect"
            stroke="#a8a29e"
            strokeDasharray="4 4"
            dot={false}
            name="ideal"
            isAnimationActive={false}
          />
          <Line
            type="linear"
            dataKey="realized"
            stroke="#0f766e"
            strokeWidth={2}
            dot={{ r: 3 }}
            name="realized"
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
