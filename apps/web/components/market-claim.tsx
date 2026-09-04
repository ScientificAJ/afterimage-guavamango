import { Panel, Badge, Metric } from "./ui";
import { compactHash } from "@/lib/format";

export function MarketClaim({ snapshot, candidate }: { snapshot?: Record<string, any>; candidate?: Record<string, any> }) {
  const features = (snapshot?.features ?? candidate?.features ?? {}) as Record<string, unknown>;
  return (
    <Panel eyebrow="01 / Point-in-time" title="Market claim" mark="⌁">
      <div className="row split"><Badge tone="verified">Frozen before outcome</Badge><code>{compactHash(snapshot?.snapshot_id)}</code></div>
      <p className="claim">A failed opening-range break re-entered its prior range. The claim is deterministic; the model can challenge it, never invent it.</p>
      <div className="metrics four">
        <Metric label="Range high" value={String(features.range_high ?? "—")} />
        <Metric label="Range low" value={String(features.range_low ?? "—")} />
        <Metric label="09:55 close" value={String(features.close_0955 ?? "—")} />
        <Metric label="Direction" value={String(candidate?.direction ?? "—")} />
      </div>
    </Panel>
  );
}
