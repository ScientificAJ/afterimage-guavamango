import type { SessionSummary } from "./event-types";

const API = process.env.NEXT_PUBLIC_AFTERIMAGE_API ?? "http://127.0.0.1:8000";

export function isPublicReplayMode(): boolean {
  if (typeof window === "undefined") return false;
  if (new URLSearchParams(window.location.search).get("demo") === "1") return true;
  return !["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
}

interface PublicReplayEnvelope {
  run_record: SessionSummary;
}

export async function runReplay(fixture: "accepted" | "rejected"): Promise<SessionSummary> {
  if (isPublicReplayMode()) {
    const response = await fetch(`/demo/${fixture}.json`, { cache: "force-cache" });
    if (!response.ok) throw new Error(`Public evidence replay failed (${response.status})`);
    const envelope = await response.json() as PublicReplayEnvelope;
    return envelope.run_record;
  }
  const response = await fetch(`${API}/api/replays`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ fixture }),
  });
  if (!response.ok) throw new Error(`Replay failed (${response.status})`);
  return response.json();
}

export async function runShadow(strategyId = "shadow_clock_shock_reversal_v1"): Promise<SessionSummary> {
  if (isPublicReplayMode()) {
    throw new Error("Live shadow is available only in the authenticated local operator cockpit.");
  }
  const response = await fetch(`${API}/api/shadow`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ strategy_id: strategyId }),
  });
  if (!response.ok) throw new Error(`Live shadow failed (${response.status})`);
  return response.json();
}

export function subscribe(
  sessionId: string,
  onEvent: (event: MessageEvent) => void,
  onComplete: () => void,
): EventSource {
  const source = new EventSource(`${API}/api/stream/${sessionId}`);
  source.addEventListener("session", onEvent);
  source.addEventListener("complete", () => {
    onComplete();
    source.close();
  });
  return source;
}
