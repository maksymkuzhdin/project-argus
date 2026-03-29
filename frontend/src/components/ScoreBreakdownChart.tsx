"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from "recharts";

interface RuleDetail {
  rule_name: string;
  score: number;
  triggered: boolean;
  explanation: string;
}

const RULE_LABELS: Record<string, string> = {
  unexplained_wealth: "Unexplained Wealth",
  cash_to_bank_ratio: "Cash Dominance",
  unknown_value_frequency: "Unknown Values",
  acquisition_income_mismatch: "Acquisition Mismatch",
};

interface Props {
  ruleDetails: RuleDetail[];
  totalScore: number;
}

export default function ScoreBreakdownChart({ ruleDetails, totalScore }: Props) {
  const data = ruleDetails.map((r) => ({
    name: RULE_LABELS[r.rule_name] || r.rule_name,
    score: r.score,
    triggered: r.triggered,
  }));
  const maxRuleScore = Math.max(...data.map((d) => d.score), 1);

  if (data.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-8">
        No scoring data available.
      </div>
    );
  }

  return (
    <div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: "#71717a", fontSize: 11 }}
            axisLine={{ stroke: "#3f3f46" }}
            tickLine={false}
          />
          <YAxis
            domain={[0, Math.ceil(maxRuleScore)]}
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
            formatter={(value) => [Number(value).toFixed(2), "Rule Points"]}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
          />
          <ReferenceLine y={0} stroke="#3f3f46" />
          <Bar dataKey="score" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={index}
                fill={entry.triggered ? "#f59e0b" : "#22c55e"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="text-center mt-2 text-xs text-zinc-500">
        Composite score:{" "}
        <span
          className={`font-mono font-medium ${
            totalScore > 0 ? "text-amber-500" : "text-emerald-500"
          }`}
        >
          {totalScore.toFixed(1)}
        </span>
      </div>
    </div>
  );
}
