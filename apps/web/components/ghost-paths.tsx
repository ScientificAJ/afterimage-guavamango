"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel, Metric, Badge } from "./ui";
import { number, percent } from "@/lib/format";

const path = [
  { t: "09:55", median: 0, lo: 0, hi: 0 },
  { t: "+15m", median: 0.34, lo: -0.28, hi: 0.92 },
  { t: "+30m", median: 0.88, lo: -0.55, hi: 1.72 },
  { t: "+60m", median: 1.62, lo: -0.72, hi: 2.68 },
  { t: "exit", median: 3.0, lo: -1, hi: 3.0 },
];

export function GhostPaths({ evidence }: { evidence?: Record<string, any> }) {
  const metrics = evidence?.metrics ?? {};
  const pass = evidence?.status === "PASS";
  return (
    <Panel eyebrow="03 / Commit → reveal" title="Ghost paths" mark="∿" className="wide">
      <div className="row split"><Badge tone={pass ? "verified" : "rejected"}>{pass ? "Evidence survived reveal" : "Gate rejected"}</Badge><span className="mono">Wilson lower bound · weighted</span></div>
      <div className="chart-wrap" aria-label="Historical twin path visualization">
        <ResponsiveContainer width="100%" height={210}>
          <AreaChart data={path} margin={{ top: 16, right: 8, bottom: 0, left: -20 }}>
            <defs><linearGradient id="cyan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#55e8dc" stopOpacity={0.35}/><stop offset="1" stopColor="#55e8dc" stopOpacity={0}/></linearGradient></defs>
            <XAxis dataKey="t" tickLine={false} axisLine={false}/><YAxis tickLine={false} axisLine={false}/><Tooltip contentStyle={{ background: "#0c1518", border: "1px solid #24434a" }}/><Area type="monotone" dataKey="median" stroke="#55e8dc" fill="url(#cyan)" strokeWidth={2}/>
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="metrics five">
        <Metric label="n / n_eff" value={`${metrics.n ?? "—"} / ${number(metrics.n_eff, 1)}`} />
        <Metric label="Target first" value={percent(metrics.target_first_probability)} />
        <Metric label="Lower bound" value={percent(metrics.lower_confidence_bound)} />
        <Metric label="Expected value" value={`${number(metrics.expected_value_r)}R`} />
        <Metric label="LOO positive" value={percent(metrics.positive_loo_fraction)} />
      </div>
    </Panel>
  );
}
