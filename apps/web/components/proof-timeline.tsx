import type { SessionEvent } from "@/lib/event-types";
import { label } from "@/lib/format";

const stages = [
  ["SNAPSHOT_FROZEN", "Market claim"],
  ["EVIDENCE_COMMITTED", "Sealed jury"],
  ["EVIDENCE_REVEALED", "Reveal"],
  ["RISK_APPROVED", "3R passport"],
  ["WARRANT_MINTED", "Warrant"],
  ["SHADOW_READY", "Broker dry-run"],
];

export function ProofTimeline({ events, state }: { events: SessionEvent[]; state: string }) {
  const reached = new Set(events.map((event) => event.state));
  const rejected = ["REJECTED", "INSUFFICIENT_EVIDENCE", "HALTED"].includes(state);
  return (
    <div className="proof-rail" aria-label="Proof pipeline">
      {stages.map(([key, title], index) => {
        const done = reached.has(key) || state === key;
        return (
          <div className={`proof-step ${done ? "done" : ""}`} key={key}>
            <span className="proof-index">{done ? "✓" : String(index + 1).padStart(2, "0")}</span>
            <div><strong>{title}</strong><small>{done ? "Cryptographically recorded" : rejected ? "Not reached" : label(key)}</small></div>
          </div>
        );
      })}
    </div>
  );
}
