import { Panel, Badge, Metric } from "./ui";

export function BrokerTruth({ events, state }: { events: Array<Record<string, any>>; state: string }) {
  const close = events.find((event) => event.event_type === "closed")?.payload;
  return (
    <Panel eyebrow="06 / Reconciled lifecycle" title="Broker truth" mark="◎">
      {close ? <><div className="row split"><Badge tone="verified">Autopsy complete</Badge><span className="mono">Recorded-paper replay</span></div><div className="broker-flow"><span>Submitted</span><i/><span>Working</span><i/><span>Filled</span><i/><span>Closed</span></div><div className="metrics two"><Metric label="Broker-like P&L" value={`$${close.broker_pnl}`} /><Metric label="Conservative P&L" value={`$${close.conservative_modeled_pnl}`} /></div></> : <div className="empty-state rejected"><span>{state.replaceAll("_", " ")}</span><p>No broker call occurred. Rejection is a successful safety outcome.</p></div>}
    </Panel>
  );
}
