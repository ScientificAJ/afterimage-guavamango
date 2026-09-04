import type { SessionSummary } from "./event-types";

const API = process.env.NEXT_PUBLIC_AFTERIMAGE_API ?? "http://127.0.0.1:8000";

export async function runReplay(fixture: "accepted" | "rejected"): Promise<SessionSummary> {
  const response = await fetch(`${API}/api/replays`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ fixture }),
  });
  if (!response.ok) throw new Error(`Replay failed (${response.status})`);
  return response.json();
}

export function subscribe(sessionId: string, onEvent: (event: MessageEvent) => void): EventSource {
  const source = new EventSource(`${API}/api/stream/${sessionId}`);
  source.addEventListener("session", onEvent);
  return source;
}
