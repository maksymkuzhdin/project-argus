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

type RuleMeta = {
  title: string;
  logic: string;
};

const RULE_META: Record<string, RuleMeta> = {
  // Legacy/basic rules
  unexplained_wealth: {
    title: "Unexplained Wealth",
    logic: "Triggers when declared assets materially exceed declared income.",
  },
  cash_to_bank_ratio: {
    title: "Cash Dominance",
    logic: "Triggers when cash is an unusually large share of monetary assets.",
  },
  unknown_value_frequency: {
    title: "Unknown Values Frequency",
    logic: "Triggers when too many key value fields are unknown/unavailable.",
  },
  acquisition_income_mismatch: {
    title: "Acquisition vs Income Mismatch",
    logic: "Triggers when a major acquisition appears too large relative to annual income.",
  },

  // Current declaration-level checks
  TQ1: { title: "Invalid/Impossible Dates", logic: "Flags malformed or out-of-range ownership/acquisition dates." },
  TQ2: { title: "Unresolved Person References", logic: "Flags ownership/person links that cannot be resolved to known household members." },
  TQ3: { title: "Implausible Ownership Shares", logic: "Flags assets where combined ownership shares look inconsistent (too high/too low)." },
  TQ4: { title: "Parse/Extreme Numeric Values", logic: "Flags non-parsable or extreme numeric values likely to distort analysis." },

  CR1: { title: "Cash vs Income", logic: "Flags high cash-to-income ratios (higher multipliers increase severity)." },
  CR2: { title: "FX Cash Dominance", logic: "Flags foreign-currency cash concentration, especially when large vs annual income." },
  CR3: { title: "Acquisitions vs Income", logic: "Flags same-year asset purchases that significantly exceed household income." },
  CR4: { title: "Low Income, Multiple Big Purchases", logic: "Flags multiple medium/high-value acquisitions in low-income years." },
  CR5: { title: "Assets Grow Faster Than Income", logic: "Flags years where assets jump while income remains flat or grows slowly." },
  CR6: { title: "Large Real-Estate Footprint", logic: "Flags unusually large residential/agricultural area holdings." },
  CR7: { title: "Vehicle Lifestyle Mismatch", logic: "Flags luxury/high-count vehicle ownership inconsistent with income profile." },
  CR8: { title: "Agri Assets Without Agri Income", logic: "Flags agricultural holdings without corresponding agri/rent/business income." },
  CR9: { title: "Rentable Assets Without Rent Income", logic: "Flags commercial/rentable property holdings with little or no rental income." },
  CR10: { title: "Unknown Valuations on Major Assets", logic: "Flags major assets repeatedly declared with unknown value." },
  CR11: { title: "Proxy Ownership Pattern", logic: "Flags major assets owned by spouse/child with low independent income." },
  CR13: { title: "Repeated Family No-Info Markers", logic: "Flags repeated key-field omissions attributed to family non-disclosure." },
  CR16: { title: "Cohort Outlier", logic: "Flags declarations that are statistical outliers versus similar peers." },

  BR2: { title: "Growing Unknown-Value Share", logic: "Flags increasing proportion of unknown/confidential values across years." },
  BR4: { title: "Post-Role-Change Asset Surge", logic: "Flags sharp asset growth after role changes/promotion periods." },
};

function getRuleMeta(ruleName: string): RuleMeta {
  return (
    RULE_META[ruleName] || {
      title: ruleName,
      logic: "Statistical check from the scoring model; review declaration-specific explanation below.",
    }
  );
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: { ruleCode: string; title: string; logic: string; explanation: string; score: number; triggered: boolean } }> }) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }

  const point = payload[0]?.payload;
  if (!point) {
    return null;
  }

  return (
    <div className="max-w-xs rounded-lg border border-zinc-600 bg-zinc-900/95 p-3 shadow-xl">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-zinc-300">
        {point.ruleCode}
      </div>
      <div className="mt-1 text-sm font-semibold text-zinc-100">{point.title}</div>
      <div className="mt-2 text-xs leading-relaxed text-zinc-200">{point.logic}</div>
      <div className="mt-2 text-xs text-zinc-300">
        Rule points: <span className="font-mono text-zinc-100">{Number(point.score).toFixed(2)}</span>
      </div>
      <div className="mt-2 text-xs text-zinc-400">{point.explanation}</div>
    </div>
  );
};

interface Props {
  ruleDetails: RuleDetail[];
  totalScore: number;
}

export default function ScoreBreakdownChart({ ruleDetails, totalScore }: Props) {
  const data = ruleDetails.map((r) => ({
    ruleCode: r.rule_name,
    name: getRuleMeta(r.rule_name).title,
    title: getRuleMeta(r.rule_name).title,
    logic: getRuleMeta(r.rule_name).logic,
    score: r.score,
    triggered: r.triggered,
    explanation: r.explanation,
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
            content={<CustomTooltip />}
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
