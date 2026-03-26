"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface Props {
  totalIncome: number;
  totalAssets: number;
  incomeCount: number;
  monetaryCount: number;
  realEstateCount: number;
}

export default function IncomeAssetsChart({
  totalIncome,
  totalAssets,
  incomeCount,
  monetaryCount,
  realEstateCount,
}: Props) {
  const data = [
    {
      name: "Declared Income",
      value: totalIncome,
      label: `${incomeCount} sources`,
    },
    {
      name: "Total Assets",
      value: totalAssets,
      label: `${monetaryCount} monetary + ${realEstateCount} properties`,
    },
  ];

  if (totalIncome === 0 && totalAssets === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-8">
        No financial data to chart.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 8, right: 24, left: 8, bottom: 4 }}
      >
        <XAxis
          type="number"
          tick={{ fill: "#71717a", fontSize: 11 }}
          axisLine={{ stroke: "#3f3f46" }}
          tickLine={false}
          tickFormatter={(v: number) =>
            v >= 1_000_000
              ? `${(v / 1_000_000).toFixed(1)}M`
              : v >= 1_000
              ? `${(v / 1_000).toFixed(0)}K`
              : v.toString()
          }
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: "#a1a1aa", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={120}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #3f3f46",
            borderRadius: "8px",
            color: "#d4d4d8",
            fontSize: "12px",
          }}
          formatter={(value) => [Number(value).toLocaleString(), "UAH"]}
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
        />
        <Bar dataKey="value" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={32} />
      </BarChart>
    </ResponsiveContainer>
  );
}
