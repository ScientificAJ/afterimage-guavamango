import { Panel, Badge } from "./ui";
import { compactHash } from "@/lib/format";

export function SealedJury({ events, agents }: { events: Array<Record<string, any>>; agents?: Record<string, any> }) {
  const commit = events.find((event) => event.event_type === "evidence_committed")?.payload ?? {};
  const reports = Object.values(agents ?? {}) as Array<Record<string, any>>;
  return (
    <Panel eyebrow="02 / Outcome blind" title="Sealed jury" mark="◇">
      <div className="seal">
        <div><span className="seal-ring">{commit.twin_count ?? 0}</span><small>historical twins</small></div>
        <div><Badge tone="pending">Outcomes hidden</Badge><code>{compactHash(commit.commit_hash)}</code></div>
      </div>
      <div className="jury-grid">
        {reports.map((report) => <article key={String(report.role)}><span>{String(report.role).replaceAll("_", " ")}</span><strong>{report.status}</strong><p>{report.thesis}</p></article>)}
      </div>
    </Panel>
  );
}
