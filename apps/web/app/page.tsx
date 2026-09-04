"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowSquareOut,
  Brain,
  Broadcast,
  CaretDown,
  ChartLineUp,
  CheckCircle,
  Cloud,
  Eye,
  Flask,
  Lightning,
  ListChecks,
  LockKey,
  PauseCircle,
  PlayCircle,
  Scales,
  ShieldCheck,
  TerminalWindow,
  TrendUp,
  XCircle,
} from "@phosphor-icons/react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { isPublicReplayMode, runReplay, runShadow, subscribe } from "@/lib/api";
import type { Gate, SessionEvent, SessionSummary } from "@/lib/event-types";

type RunMode = "accepted" | "rejected" | "live";

interface BrokerAccount {
  cash?: string | number;
  equity?: string | number;
  last_equity?: string | number;
  options_approved_level?: number;
  options_trading_level?: number;
  paper?: boolean;
  status?: string;
  timestamp?: string;
  trading_blocked?: boolean;
}

interface Position {
  symbol?: string;
  avg_entry_price?: string | number;
  current_price?: string | number;
  qty?: string | number;
  unrealized_pl?: string | number;
}

const STRATEGY_ID = "shadow_clock_shock_reversal_v1";
const STARTING_BALANCE = 100_000;

const RESEARCH = [
  { label: "TRADES", value: "95" },
  { label: "NET RESULT", value: "+48.05R" },
  { label: "PROFIT FACTOR", value: "2.253" },
  { label: "EXPECTANCY", value: "+0.506R" },
  { label: "MAX DRAWDOWN", value: "4.746R" },
  { label: "POSITIVE NEIGHBORS", value: "108 / 108" },
];

const PIPELINE = [
  { label: "MARKET DATA", note: "ALPACA / IEX", icon: Cloud },
  { label: "SIGNAL", note: "GUAVAMANGO", icon: TrendUp },
  { label: "AI JURY", note: "4 AGENTS", icon: Brain },
  { label: "CRITIC", note: "FALSIFY FIRST", icon: Scales },
  { label: "RISK ENGINE", note: "DETERMINISTIC", icon: ShieldCheck },
  { label: "ALPACA", note: "PAPER ONLY", icon: Lightning },
];

function asNumber(value: unknown, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function money(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function latestEvent(session: SessionSummary | null, eventType: string) {
  return session?.events.filter((event) => event.event_type === eventType).at(-1);
}

function accountFrom(session: SessionSummary | null): BrokerAccount {
  const precheck = latestEvent(session, "precheck_passed");
  const eventAccount = precheck?.payload.account;
  if (eventAccount && typeof eventAccount === "object") return eventAccount as BrokerAccount;
  const brokerAccount = session?.broker?.account;
  if (brokerAccount && typeof brokerAccount === "object") return brokerAccount as BrokerAccount;
  return { equity: STARTING_BALANCE, last_equity: STARTING_BALANCE, paper: true, status: "ACTIVE" };
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventReason(session: SessionSummary | null, mode: RunMode) {
  if (mode !== "live") {
    return mode === "accepted"
      ? "Recorded evidence cleared every gate, but execution remained disabled. No broker order or P&L is claimed."
      : "Recorded evidence was rejected before an order could be constructed. The failed gate remains visible for audit.";
  }
  const noSignal = session?.events.find((event) => ["no_signal", "skipped", "candidate_rejected"].includes(event.event_type));
  if (noSignal) {
    const reason = noSignal.payload.reason ?? noSignal.payload.reason_code ?? noSignal.payload.message;
    if (typeof reason === "string") return humanize(reason);
  }
  if (session?.candidate) return "A candidate was observed. AI and deterministic risk evidence are shown below; no fill is assumed.";
  return "The scanner found no qualifying setup. The correct autonomous action is to preserve capital and wait.";
}

function marketState(now: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const part = (name: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === name)?.value ?? "";
  const weekday = part("weekday");
  const minutes = asNumber(part("hour")) * 60 + asNumber(part("minute"));
  return !["Sat", "Sun"].includes(weekday) && minutes >= 570 && minutes < 960 ? "MARKET OPEN" : "MARKET CLOSED";
}

function agentEntries(session: SessionSummary | null) {
  const order = ["strategist", "regime_witness", "options_witness", "execution_witness", "prosecutor"];
  return Object.entries(session?.agents ?? {})
    .sort(([left], [right]) => order.indexOf(left) - order.indexOf(right))
    .slice(0, 4)
    .map(([name, raw]) => {
    const report = raw as Record<string, unknown>;
    return {
      name: name === "options_witness" ? "Execution Witness" : humanize(name),
      status: String(report.status ?? "standby").toUpperCase(),
      thesis: String(report.thesis ?? "Awaiting a qualifying market packet."),
      model: name === "strategist" || name === "prosecutor" ? "GLM-5.3" : "GLM-5.3-Flash",
    };
  });
}

function gateStage(session: SessionSummary | null, index: number) {
  if (!session) return "idle";
  if (index < 2 && session.snapshot) return "pass";
  if (index === 2 && session.agents) return "pass";
  if (index === 3 && session.evidence) return session.evidence.status === "PASS" ? "pass" : "fail";
  if (index === 4 && session.risk) return session.risk.status === "PASS" ? "pass" : "fail";
  if (index === 5 && session.broker) return "pass";
  return "idle";
}

function StatusIcon({ state }: { state: "pass" | "fail" | "idle" }) {
  if (state === "pass") return <CheckCircle weight="fill" aria-label="passed" />;
  if (state === "fail") return <XCircle weight="fill" aria-label="failed" />;
  return <span className="idle-dot" aria-label="not reached" />;
}

export default function Home() {
  const [mode, setMode] = useState<RunMode>("accepted");
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [streamed, setStreamed] = useState(false);
  const [publicReplay, setPublicReplay] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const stream = useRef<EventSource | null>(null);

  const run = useCallback(async (next: RunMode) => {
    setLoading(true);
    setError("");
    setMode(next);
    setStreamed(false);
    stream.current?.close();
    try {
      const publicMode = isPublicReplayMode();
      setPublicReplay(publicMode);
      const result = next === "live" ? await runShadow(STRATEGY_ID) : await runReplay(next);
      setSession(result);
      if (publicMode) setStreamed(true);
      else {
        stream.current = subscribe(
          result.session_id,
          (message) => {
            const event = JSON.parse(message.data) as SessionEvent;
            setSession((current) => current
              ? {
                  ...current,
                  events: [...current.events.filter((item) => item.sequence !== event.sequence), event]
                    .sort((a, b) => a.sequence - b.sequence),
                }
              : current);
          },
          () => setStreamed(true),
        );
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The evidence service is unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const initial = query.get("session") === "rejected" ? "rejected" : "accepted";
    void run(initial);
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => {
      window.clearInterval(timer);
      stream.current?.close();
    };
  }, [run]);

  const account = accountFrom(session);
  const equity = asNumber(account.equity, STARTING_BALANCE);
  const totalPnl = equity - STARTING_BALANCE;
  const pnlPercent = (totalPnl / STARTING_BALANCE) * 100;
  const agents = agentEntries(session);
  const researchConfidence = session?.evidence?.metrics?.confidence_method
    ? String(session.evidence.metrics.confidence_method).replace("one-sided Wilson ", "")
    : null;
  const gates = session?.risk?.gates ?? [];
  const passedGates = gates.filter((gate) => gate.passed).length;
  const positions = useMemo(() => {
    const raw = session?.broker?.positions;
    return Array.isArray(raw) ? raw as Position[] : [];
  }, [session]);
  const generatedAt = account.timestamp ?? session?.events.at(-1)?.created_at;
  const status = loading ? "RUNNING" : "PAUSED";
  const market = marketState(now);
  const accountChart = [
    { label: "START", equity: STARTING_BALANCE },
    { label: "NOW", equity },
  ];

  return (
    <main className="flight-deck" id="top">
      <header className="site-header">
        <a className="wordmark" href="#top" aria-label="Afterimage GuavaMango cockpit">
          <span>AFTERIMAGE</span><i>/</i><strong>GUAVA<span>MANGO</span></strong>
        </a>
        <nav aria-label="Primary navigation">
          <a className="active" href="#cockpit">Cockpit</a>
          <a href="#decisions">Decisions</a>
          <a href="#options">Options</a>
          <a href="#architecture">Architecture</a>
        </nav>
        <div className={`agent-state ${loading ? "is-running" : ""}`} aria-live="polite">
          {loading ? <PlayCircle weight="fill" /> : <PauseCircle weight="fill" />}
          <strong>AGENT {status} · {market}</strong>
        </div>
        <div className="broker-chip">
          <CheckCircle weight="fill" />
          <span>Alpaca Paper<small>{account.status === "ACTIVE" ? "CONNECTED" : "RECORDED"}</small></span>
        </div>
      </header>

      <section className="cockpit-grid" id="cockpit">
        <article className="account-board">
          <img className="mango-orbit" src="/assets/mango-orbit.png" alt="" aria-hidden="true" />
          <span className="outline-label">PAPER ACCOUNT</span>
          <div className="account-value">{money(equity).replace("$", "$").split(".")[0]}<small>.{money(equity).split(".")[1]}</small></div>
          <div className="account-metrics">
            <div><span>STARTING BALANCE</span><strong>{money(STARTING_BALANCE)}</strong></div>
            <div><span>CURRENT EQUITY</span><strong>{money(equity)}</strong></div>
            <div className={totalPnl >= 0 ? "positive" : "negative"}><span>TOTAL BROKER P&amp;L</span><strong>{money(totalPnl)}</strong><small>{pnlPercent >= 0 ? "+" : ""}{pnlPercent.toFixed(2)}%</small></div>
          </div>
          <div className="equity-chart" role="img" aria-label={`Paper account equity is ${money(equity)} from a ${money(STARTING_BALANCE)} start`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={accountChart} margin={{ top: 10, right: 18, bottom: 0, left: 8 }}>
                <CartesianGrid vertical={false} stroke="#d8d7d2" strokeDasharray="2 3" />
                <YAxis domain={[STARTING_BALANCE - 50, Math.max(STARTING_BALANCE + 50, equity + 50)]} hide />
                <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#6f6c67" }} />
                <ReferenceLine y={STARTING_BALANCE} stroke="#f2aa00" strokeDasharray="4 3" />
                <Line type="linear" dataKey="equity" stroke="#11110f" strokeWidth={2} dot={{ r: 4, fill: "#f2aa00", stroke: "#fff", strokeWidth: 2 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="account-foot">
            <em>{totalPnl === 0 ? "No closed paper trades yet." : "Broker-reported paper equity."}</em>
            <span>{generatedAt ? new Date(generatedAt).toLocaleString("en-US", { timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short" }) + " ET" : "Awaiting first broker snapshot"}</span>
          </div>
          <div className="research-strip">
            <strong>RESEARCH EVIDENCE</strong>
            {RESEARCH.slice(0, 4).map((item) => <span key={item.label}>{item.value}</span>)}
            <a href="#research">FULL STUDY <ArrowSquareOut /></a>
          </div>
        </article>

        <article className="decision-board" id="decisions">
          <img className="decision-radar" src="/assets/decision-radar.png" alt="" aria-hidden="true" />
          <div className="section-title"><span>LATEST AI DECISION</span><small>{mode === "live" ? "LIVE SHADOW" : "SIGNED REPLAY"}</small></div>
          <h1>NO LIVE TRADE</h1>
          <div className="confidence"><span>Decision confidence</span><strong>UNSCORED</strong><small>No fabricated probability</small></div>
          <p className="decision-copy">{eventReason(session, mode)}</p>
          {researchConfidence && <div className="confidence-note"><LockKey /> Evidence interval method: <b>{researchConfidence}</b></div>}
          <div className="jury-row">
            {(agents.length ? agents : [
              { name: "Strategist", status: "STANDBY", thesis: "Awaiting a qualifying market packet.", model: "GLM-5.3" },
              { name: "Regime Witness", status: "STANDBY", thesis: "Awaiting a qualifying market packet.", model: "GLM-5.3-Flash" },
              { name: "Execution Witness", status: "STANDBY", thesis: "Awaiting a qualifying market packet.", model: "GLM-5.3-Flash" },
              { name: "Prosecutor", status: "STANDBY", thesis: "Awaiting a qualifying market packet.", model: "GLM-5.3" },
            ]).map((agent, index) => {
              const Icon = [Brain, Eye, Lightning, Scales][index] ?? Brain;
              return <article key={agent.name}>
                <Icon weight="duotone" />
                <div><span>{agent.name}</span><strong>{agent.status}</strong><small>{agent.model}</small></div>
                <p>{agent.thesis}</p>
              </article>;
            })}
          </div>
        </article>
      </section>

      {error && (
        <div className="service-notice" role="alert">
          <Broadcast />
          <strong>Evidence service offline</strong>
          <span>{error}</span>
          <code>uv run afterimage serve</code>
        </div>
      )}

      <section className="pipeline" id="architecture" aria-label="Agent workflow">
        {PIPELINE.map(({ label, note, icon: Icon }, index) => {
          const stage = gateStage(session, index);
          return <div className={`pipeline-step ${stage}`} key={label}>
            <Icon weight="duotone" />
            <div><strong>{label}</strong><small>{note}</small></div>
            <StatusIcon state={stage} />
            {index < PIPELINE.length - 1 && <ArrowRight className="pipeline-arrow" />}
          </div>;
        })}
        <div className="pipeline-meta"><span>RUN</span><strong>{session?.events.length ?? 0} events</strong><small>{streamed ? "AUDIT COMPLETE" : "STREAMING"}</small></div>
      </section>

      <section className="lower-grid">
        <div className="left-stack">
          <section className="positions-panel data-panel" id="positions">
            <div className="panel-title"><h2>CURRENT POSITIONS</h2><span><Broadcast weight="fill" /> REAL-TIME</span></div>
            <div className="table-head positions-head"><span>SYMBOL</span><span>ENTRY</span><span>CURRENT</span><span>SIZE</span><span>P&amp;L</span></div>
            {positions.length ? positions.map((position) => (
              <div className="table-row positions-head" key={position.symbol}>
                <strong>{position.symbol}</strong><span>{money(asNumber(position.avg_entry_price))}</span><span>{money(asNumber(position.current_price))}</span><span>{position.qty}</span><b>{money(asNumber(position.unrealized_pl))}</b>
              </div>
            )) : (
              <div className="empty-position"><ChartLineUp weight="thin" /><p>No open paper positions</p><small>First broker-backed position will appear here automatically.</small></div>
            )}
          </section>

          <section className="history-panel data-panel" id="history">
            <div className="panel-title"><h2>TRADE HISTORY</h2><span><Broadcast weight="fill" /> BROKER TRUTH</span></div>
            <div className="table-head history-head"><span>TIME (ET)</span><span>SIDE</span><span>SYMBOL</span><span>INSTRUMENT</span><span>RESULT</span><span>BROKER STATUS</span></div>
            <div className="empty-history"><ListChecks weight="thin" /><span>No broker fills yet. Recorded replays never enter this ledger.</span></div>
          </section>
        </div>

        <section className="risk-panel data-panel" id="risk">
          <div className="panel-title"><h2>RISK PASSPORT</h2><span>{mode === "live" ? "LIVE" : "REPLAY"}</span></div>
          <dl className="risk-list">
            <div><dt>Trade permission</dt><dd className={session?.risk?.status === "PASS" ? "good" : "quiet"}>{session?.risk?.status ?? "NOT REQUESTED"}</dd></div>
            <div><dt>Position sizing</dt><dd>{mode === "live" && session?.risk ? `${session.risk.quantity} units` : "0 active"}</dd></div>
            <div><dt>Stop loss</dt><dd>{mode === "live" && session?.payoff?.operational_stop_loss ? money(asNumber(session.payoff.operational_stop_loss)) : "—"}</dd></div>
            <div><dt>Target : risk floor</dt><dd className="good">≥ 3.00R</dd></div>
            <div><dt>Portfolio exposure</dt><dd>{positions.length ? "Broker-linked" : "0.00%"}</dd></div>
            <div><dt>Gate coverage</dt><dd>{gates.length ? `${passedGates} / ${gates.length}` : "Awaiting setup"}</dd></div>
          </dl>
          <details>
            <summary>Inspect deterministic gates <CaretDown /></summary>
            <div className="gate-list">
              {gates.length ? gates.map((gate: Gate) => <div key={gate.name}><span>{humanize(gate.name)}</span><b className={gate.passed ? "good" : "bad"}>{gate.passed ? "PASS" : "FAIL"}</b><small>{gate.observed} / {gate.required}</small></div>) : <p>No gate packet exists because there is no active candidate.</p>}
            </div>
          </details>
          <footer><ShieldCheck weight="duotone" /><span>SIGNED RISK WARRANT</span><strong>{session?.warrant ? "MINTED IN REPLAY" : "NOT MINTED"}</strong></footer>
        </section>

        <section className="options-lab" id="options">
          <img className="coral-orbit" src="/assets/coral-orbit.png" alt="" aria-hidden="true" />
          <div className="options-copy">
            <div className="options-title"><h2>OPTIONS LAB</h2><span>MULTI-LEG READY</span><b>LEVEL {account.options_trading_level ?? account.options_approved_level ?? 3}</b></div>
            <strong>CALL / PUT /<br/>DEBIT VERTICAL</strong>
            <p className="no-order">NO OPTION ORDER ACTIVE</p>
            <p>Options tooling is integrated for research and replay. GuavaMango’s active winner is a long-only equity strategy.</p>
            <div className="option-truth"><Flask /> CAPABILITY, NOT CLAIMED P&amp;L</div>
          </div>
          <div className="payoff-plot" aria-label="Illustrative normalized debit spread payoff profile">
            <div className="payoff-label profit">PROFIT</div>
            <div className="payoff-label loss">LOSS</div>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={[
                { price: 80, payoff: -1 }, { price: 92, payoff: -1 }, { price: 100, payoff: 0 }, { price: 108, payoff: 1 }, { price: 120, payoff: 1 },
              ]} margin={{ top: 28, right: 18, bottom: 18, left: 18 }}>
                <CartesianGrid stroke="#d8d7d2" strokeDasharray="2 3" />
                <XAxis dataKey="price" axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "#5f5b55" }} />
                <YAxis hide domain={[-1.3, 1.3]} />
                <ReferenceLine y={0} stroke="#77736d" />
                <Line type="linear" dataKey="payoff" stroke="#06813e" strokeWidth={3} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
            <small>ILLUSTRATIVE NORMALIZED PAYOFF · NOT AN ACTIVE POSITION</small>
          </div>
        </section>

        <section className="research-panel" id="research">
          <div className="panel-title"><h2>GUAVAMANGO RESEARCH</h2><span>OUT-OF-SAMPLE STRESS</span></div>
          <div className="research-grid">
            {RESEARCH.map((item) => <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}
          </div>
          <p>Eight profitable underlyings · 72.34% positive active months · PF 2.222 at 1.5× modeled costs. Research statistics are not broker returns.</p>
        </section>

        <section className="how-panel" aria-labelledby="how-title">
          <div className="panel-title"><h2 id="how-title">HOW IT WORKS</h2><span>VERIFIABLE STACK</span></div>
          <div className="how-flow">
            <div><Cloud weight="duotone" /><span>01</span><strong>ALPACA<br/>TRADING API</strong></div><ArrowRight />
            <div><TerminalWindow weight="duotone" /><span>02</span><strong>OFFICIAL<br/>MCP / CLI</strong></div><ArrowRight />
            <div><Brain weight="duotone" /><span>03</span><strong>GLM-5.3 +<br/>GLM-5.3-FLASH</strong></div><ArrowRight />
            <div><ShieldCheck weight="duotone" /><span>04</span><strong>SIGNED<br/>RISK WARRANT</strong></div>
          </div>
          <div className="run-controls" role="group" aria-label="Evidence run mode">
            <button className={mode === "accepted" ? "active" : ""} onClick={() => void run("accepted")}>Accepted proof</button>
            <button className={mode === "rejected" ? "active" : ""} onClick={() => void run("rejected")}>Rejection proof</button>
            <button className={mode === "live" ? "active" : ""} onClick={() => void run("live")} disabled={publicReplay} title={publicReplay ? "Live shadow is available in the authenticated local cockpit" : undefined}>Run live shadow</button>
          </div>
        </section>
      </section>

      <footer className="legal-footer">
        <span>AFTERIMAGE / GUAVAMANGO</span>
        <p>Paper trading only. Research evidence is separated from broker P&amp;L. No performance guarantee or financial advice.</p>
        <code>{STRATEGY_ID}</code>
      </footer>
    </main>
  );
}
