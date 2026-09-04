import { Panel, Badge } from "./ui";
import { compactHash } from "@/lib/format";

export function WarrantCard({ warrant }: { warrant?: Record<string, any> }) {
  return (
    <Panel eyebrow="05 / Single-use authority" title="Execution warrant" mark="✦">
      {warrant ? <>
        <div className="warrant-head"><Badge tone="verified">Ed25519 signed</Badge><span>TTL-bound · exact intent</span></div>
        <dl className="hash-list"><div><dt>Intent</dt><dd>{compactHash(warrant.intent_hash, 10)}</dd></div><div><dt>Risk vector</dt><dd>{compactHash(warrant.risk_vector_hash, 10)}</dd></div><div><dt>Nonce</dt><dd>{compactHash(warrant.nonce, 10)}</dd></div><div><dt>Signature</dt><dd>{compactHash(warrant.signature, 10)}</dd></div></dl>
        <p className="microcopy">Change one leg, price, account, quantity, evidence hash, or deadline—and the signature fails.</p>
      </> : <div className="empty-state"><span>Warrant not minted</span><p>A rejected trial can never recover execution authority.</p></div>}
    </Panel>
  );
}
