import { Panel } from "./ui";

export function Graveyard({ tournament }: { tournament?: Record<string, any> }) {
  const dead = ((tournament?.entries ?? []) as Array<Record<string, any>>).filter((entry) => entry.status !== "PASS");
  return <Panel eyebrow="Anti-cherry-picking" title="Alpha graveyard" mark="†"><div className="graveyard">{dead.map((entry) => <article key={entry.manifest_hash}><span>ARCHIVED</span><strong>{entry.identity.strategy_id.replaceAll("_", " ")}</strong><p>{(entry.failed_gates ?? []).join(" · ") || "Failed promotion policy"}</p></article>)}{!dead.length && <div className="empty-state"><span>Awaiting reveal</span></div>}</div></Panel>;
}
