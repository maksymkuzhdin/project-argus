"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

const RULE_LABELS: Record<string, string> = {
  unexplained_wealth: "Unexplained Wealth",
  cash_to_bank_ratio: "Cash Dominance",
  unknown_value_frequency: "Unknown Values",
  acquisition_income_mismatch: "Acquisition Mismatch",
};

interface Props {
  ruleDistribution: Record<string, number>;
}

export default function RuleDistributionChart({ ruleDistribution }: Props) {
  const data = Object.entries(ruleDistribution).map(([key, value]) => ({
    name: RULE_LABELS[key] || key,
    count: value,
  }));

  if (data.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-8">
        No triggered rules to display.
      </div>
    );
  }

  const COLORS = ["#f59e0b", "#ef4444", "#8b5cf6", "#3b82f6"];

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <XAxis
          dataKey="name"
          tick={{ fill: "#71717a", fontSize: 11 }}
          axisLine={{ stroke: "#3f3f46" }}
          tickLine={false}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fill: "#71717a", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={36}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#18181b",
            border: "1px solid #3f3f46",
            borderRadius: "8px",
            color: "#d4d4d8",
            fontSize: "12px",
          }}
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
        />
        <Bar dataKey="count" radius={[4, 4, 0, 0]}>
          {data.map((_entry, index) => (
            <Cell key={index} fill={COLORS[index % COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
