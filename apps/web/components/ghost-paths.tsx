"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel, Metric, Badge } from "./ui";
import { number, percent } from "@/lib/format";

export function GhostPaths({ evidence, paths = [], mode }: { evidence?: Record<string, any>; paths?: Array<{ step: number; low: string; median: string; high: string }>; mode: string }) {
  const metrics = evidence?.metrics ?? {};
  const pass = evidence?.status === "PASS";
  const chart = paths.map((point) => ({ ...point, t: point.step === 0 ? "entry" : `step ${point.step}` }));
  return (
    <Panel eyebrow="03 / Commit → reveal" title="Ghost paths" mark="∿" className="wide">
      <div className="row split"><Badge tone={pass ? "verified" : "rejected"}>{pass ? "Evidence survived reveal" : "Gate rejected"}</Badge><span className="mono">Wilson lower bound · weighted</span></div>
      <div className="chart-wrap" aria-label={mode === "recorded-replay" ? "Synthetic engineering fixture path visualization" : "Real Alpaca training path visualization"}>
        <ResponsiveContainer width="100%" height={210}>
          <AreaChart data={chart} margin={{ top: 16, right: 8, bottom: 0, left: -20 }}>
            <defs><linearGradient id="cyan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#55e8dc" stopOpacity={0.35}/><stop offset="1" stopColor="#55e8dc" stopOpacity={0}/></linearGradient></defs>
            <XAxis dataKey="t" tickLine={false} axisLine={false}/><YAxis tickLine={false} axisLine={false}/><Tooltip contentStyle={{ background: "#0c1518", border: "1px solid #24434a" }}/><Area type="monotone" dataKey="high" stroke="transparent" fill="rgba(85,232,220,.08)"/><Area type="monotone" dataKey="median" stroke="#55e8dc" fill="url(#cyan)" strokeWidth={2}/><Area type="monotone" dataKey="low" stroke="#ff6c69" fill="transparent" strokeDasharray="3 4"/>
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
