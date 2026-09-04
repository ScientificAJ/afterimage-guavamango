import { Panel, Badge, Metric } from "./ui";

export function BrokerTruth({ broker, dryRun, state, mode, marketData }: { broker?: Record<string, any>; dryRun?: Record<string, any>; state: string; mode: string; marketData?: Record<string, any> }) {
  const connected = broker?.connected === true;
  return (
    <Panel eyebrow="06 / Reconciled lifecycle" title="Broker truth" mark="◎">
      {connected ? <><div className="row split"><Badge tone="verified">Paper account connected</Badge><span className="mono">{String(broker?.transport ?? "Alpaca")}</span></div><div className="broker-flow"><span>Read account</span><i/><span>Read market</span><i/><span>Risk gate</span><i/><span>{dryRun ? "Dry-run valid" : "No order"}</span></div><div className="metrics four"><Metric label="Order sent" value={broker?.order_sent ? "YES" : "NO"}/><Metric label="Positions" value={String(broker?.positions ?? 0)}/><Metric label="Open orders" value={String(broker?.open_orders ?? 0)}/><Metric label="Bars / contracts" value={`${marketData?.bar_count ?? "—"} / ${marketData?.contract_count ?? "—"}`}/></div></> : <div className="empty-state"><span>{state.replaceAll("_", " ")}</span><p>{mode === "recorded-replay" ? "Recorded replay only. No broker API or broker P&L is claimed." : "The safety pipeline stopped before any order submission."}</p></div>}
    </Panel>
  );
}
