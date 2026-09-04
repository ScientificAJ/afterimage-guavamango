"use client";

import { useCallback, useEffect, useState } from "react";
import { runReplay } from "@/lib/api";
import type { SessionSummary } from "@/lib/event-types";
import { compactHash } from "@/lib/format";
import { ProofTimeline } from "@/components/proof-timeline";
import { MarketClaim } from "@/components/market-claim";
import { SealedJury } from "@/components/sealed-jury";
import { GhostPaths } from "@/components/ghost-paths";
import { RiskPassport } from "@/components/risk-passport";
import { WarrantCard } from "@/components/warrant-card";
import { BrokerTruth } from "@/components/broker-truth";
import { Tournament } from "@/components/tournament";
import { Graveyard } from "@/components/graveyard";
import { Badge } from "@/components/ui";

export default function Home() {
  const [fixture, setFixture] = useState<"accepted" | "rejected">("accepted");
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const replay = useCallback(async (next: "accepted" | "rejected") => {
    setLoading(true); setError(""); setFixture(next);
    try { setSession(await runReplay(next)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "The evidence service is unavailable."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void replay(new URLSearchParams(window.location.search).get("session") === "rejected" ? "rejected" : "accepted"); }, [replay]);

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Afterimage home"><span className="brand-mark">A/</span><div><strong>AFTERIMAGE</strong><small>VERIFIABLE AUTONOMOUS EXECUTION</small></div></a>
        <div className="system-status"><Badge tone="verified">Paper only</Badge><span>Alpaca MCP boundary</span><span>Level 3</span><span>$500 max risk</span></div>
        <div className="fixture-switch" role="group" aria-label="Replay fixture"><button className={fixture === "accepted" ? "active" : ""} onClick={() => void replay("accepted")}>Accepted proof</button><button className={fixture === "rejected" ? "active" : ""} onClick={() => void replay("rejected")}>Rejection proof</button></div>
      </header>

      <div className="hero" id="top">
        <div><p className="kicker">THE TRADE IS THE LAST STEP OF THE PROOF</p><h1>An agent that must<br/><em>earn permission</em> to act.</h1><p>AFTERIMAGE seals its historical jury before seeing outcomes, exposes every losing experiment, and signs only the exact order that survives deterministic risk.</p></div>
        <aside><span>SESSION / {session ? compactHash(session.session_id, 6) : "connecting"}</span><strong className={session?.state === "AUTOPSY" ? "ok" : "warn"}>{loading ? "REPLAYING" : session?.state?.replaceAll("_", " ") ?? "OFFLINE"}</strong><small>{session?.audit?.valid ? "Audit chain verified" : "Waiting for verification"}</small></aside>
      </div>

      {error ? <div className="connection-error"><strong>Backend not connected.</strong><span>{error}</span><code>uv run afterimage serve</code></div> : session && <>
        <ProofTimeline events={session.events} state={session.state}/>
        <div className="desk-grid">
          <MarketClaim snapshot={session.snapshot} candidate={session.candidate}/>
          <SealedJury events={session.events} agents={session.agents}/>
          <GhostPaths evidence={session.evidence}/>
          <RiskPassport payoff={session.payoff} risk={session.risk}/>
          <WarrantCard warrant={session.warrant}/>
          <BrokerTruth events={session.events} state={session.state}/>
          <Tournament tournament={session.tournament}/>
          <Graveyard tournament={session.tournament}/>
        </div>
      </>}
      <footer><span>Recorded evidence, not financial advice or claimed live returns.</span><span>Strategy logic is replaceable. Proof architecture is permanent.</span></footer>
    </main>
  );
}
