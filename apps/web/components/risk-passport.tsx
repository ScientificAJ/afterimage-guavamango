import { Panel, Badge, Metric } from "./ui";
import { number } from "@/lib/format";
import type { Gate } from "@/lib/event-types";

export function RiskPassport({ payoff, risk }: { payoff?: Record<string, any>; risk?: Record<string, any> }) {
  const gates = (risk?.gates ?? []) as Gate[];
  const failed = gates.filter((gate) => !gate.passed);
  const evaluated = Boolean(risk);
  return (
    <Panel eyebrow="04 / Deterministic policy" title="3R passport" mark="▱">
      <div className="row split"><Badge tone={!evaluated || failed.length ? "rejected" : "verified"}>{!evaluated ? "Not evaluated" : failed.length ? `${failed.length} gate failures` : `${gates.length} gates passed`}</Badge><span className="mono">LLM authority: zero</span></div>
      <div className="ratio"><div><span>Operational reward / risk</span><strong>{number(payoff?.operational_ratio)}×</strong></div><div className="ratio-line"><i style={{ width: `${Math.min(100, Number(payoff?.operational_ratio ?? 0) / 4 * 100)}%` }}/></div><small>Minimum authorization threshold 3.00× after costs</small></div>
      <div className="metrics three">
        <Metric label="Entry debit" value={`$${number(payoff?.entry_net_debit)}`} />
        <Metric label="Modeled max loss" value={`$${number(risk?.modeled_max_loss)}`} />
        <Metric label="Quantity" value={risk?.quantity ?? "—"} />
      </div>
      <details><summary>Inspect the full risk vector</summary><div className="gate-list">{gates.map((gate) => <div key={gate.name}><span>{gate.passed ? "✓" : "×"} {gate.name.replaceAll("_", " ")}</span><code>{gate.observed}</code></div>)}</div></details>
    </Panel>
  );
}
