import { Panel, Badge } from "./ui";

export function Tournament({ tournament }: { tournament?: Record<string, any> }) {
  const entries = (tournament?.entries ?? []) as Array<Record<string, any>>;
  return (
    <Panel eyebrow="Strategy laboratory" title="Sealed tournament" mark="△" className="wide">
      <div className="row split"><p className="claim small">Same untouched holdout. Same costs. Pre-registered gates. One champion—or none.</p><Badge tone={tournament?.champion ? "verified" : "pending"}>{tournament?.champion ? "Champion promoted" : "No champion"}</Badge></div>
      <div className="tournament-table"><div className="table-head"><span>Candidate</span><span>EV</span><span>Lower bound</span><span>Decision</span></div>{entries.map((entry, index) => <div key={entry.manifest_hash}><span><b>{String(index + 1).padStart(2, "0")}</b>{entry.identity.strategy_id.replaceAll("_", " ")}</span><span>{entry.metrics.expected_value_r}R</span><span>{entry.metrics.lower_confidence_bound}</span><span><Badge tone={entry.status === "PASS" ? "verified" : "rejected"}>{entry.status}</Badge></span></div>)}</div>
    </Panel>
  );
}
