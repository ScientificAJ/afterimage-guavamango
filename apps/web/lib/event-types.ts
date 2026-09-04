export type Tone = "verified" | "pending" | "rejected" | "neutral";

export interface SessionEvent {
  sequence: number;
  event_type: string;
  state: string;
  evidence_level: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Gate {
  name: string;
  passed: boolean;
  observed: string;
  required: string;
  reason_code?: string | null;
}

export interface SessionSummary {
  session_id: string;
  state: string;
  mode: string;
  events: SessionEvent[];
  audit: { valid: boolean; records?: number; reason?: string | null };
  snapshot?: Record<string, unknown>;
  candidate?: Record<string, unknown>;
  agents?: Record<string, unknown>;
  evidence?: Record<string, any>;
  payoff?: Record<string, any>;
  risk?: { status: string; quantity: number; modeled_max_loss: string; gates: Gate[] };
  warrant?: Record<string, any>;
  tournament?: Record<string, any>;
}
