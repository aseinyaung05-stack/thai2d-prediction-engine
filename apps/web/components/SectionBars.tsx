"use client";

import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface SectionDatum {
  section: string;
  probability: number; // 0..1
}

const COLORS: Record<string, string> = {
  A: "#3b82f6",
  B: "#22c55e",
  C: "#f59e0b",
  D: "#ef4444",
};

/** Horizontal bar chart of four-section model scores (A/B/C/D). */
export default function SectionBars({ data }: { data: SectionDatum[] }) {
  const chartData = [...data]
    .sort((a, b) => a.section.localeCompare(b.section))
    .map((d) => ({ ...d, pct: +(d.probability * 100).toFixed(2) }));

  const best = chartData.reduce(
    (m, d) => (d.probability > m.probability ? d : m),
    chartData[0] ?? { section: "A", probability: 0, pct: 0 }
  );

  return (
    <div className="h-52 w-full" data-testid="section-bars">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ left: -18, right: 42 }}>
          <XAxis type="number" domain={[0, 50]} hide />
          <YAxis
            type="category"
            dataKey="section"
            tick={{ fill: "#94a3b8", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={40}
          />
          <Tooltip
            cursor={{ fill: "rgba(148,163,184,0.08)" }}
            contentStyle={{
              background: "#111a2e",
              border: "1px solid #1e2b4d",
              borderRadius: 8,
              fontSize: 12,
              color: "#e2e8f0",
            }}
            formatter={(v: number) => [`${v.toFixed(2)}%`, "model score"]}
          />
          <Bar dataKey="pct" radius={[0, 6, 6, 0]} barSize={26}>
            {chartData.map((d) => (
              <Cell
                key={d.section}
                fill={COLORS[d.section] ?? "#64748b"}
                opacity={d.section === best?.section ? 1 : 0.55}
              />
            ))}
            <LabelList
              dataKey="pct"
              position="right"
              formatter={(v: number) => `${v}%`}
              style={{ fill: "#cbd5e1", fontSize: 11 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
