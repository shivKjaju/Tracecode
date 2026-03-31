/**
 * api.ts — Typed API client for the Tracecode FastAPI backend.
 *
 * All functions return plain data objects (no Axios/React Query wrapper).
 * In production the Next.js static export talks to the FastAPI server
 * on the same host. In dev, next.config.js proxies /api/* to port 7842.
 */

export interface Anomaly {
  id: string;
  label: string;
  detail: string;
  severity: "major" | "minor" | "caution";
}

export interface FileTouch {
  id: number;
  file_path: string;
  touch_count: number;
  first_touch_at: number;
  last_touch_at: number;
  persisted: number | null;
  is_hot: boolean;
}

export interface RiskyCommand {
  id: number;
  command: string;
  tier: "catastrophic" | "risky";
  reason: string;
  flagged_at: number;
}

export interface OutcomeSignal {
  label: string;
  passed: boolean;
  reliable: boolean;
}

export interface SessionSummary {
  id: string;
  started_at: number;
  ended_at: number | null;
  project_name: string;
  project_path: string;
  git_branch: string | null;
  git_commit_before: string | null;
  git_commit_after: string | null;
  claude_exit_code: number | null;
  files_touched: number | null;
  hot_files: number | null;
  commits_during: number | null;
  tree_dirty: number | null;
  persistence_rate: number | null;
  persistence_reliable: number | null;
  test_outcome: string | null;
  test_source: string | null;
  wandering_score: number | null;
  outcome_score: number | null;
  quality_score: number | null;
  auto_outcome: string | null;
  manual_outcome: string | null;
  note: string | null;
  perceived_quality: number | null;
  duration_seconds: number | null;
  ignored_touches: number | null;
  risky_count: number;
  catastrophic_count: number;
  verdict: string | null;
  sensitive_files_touched: number | null;
}

export interface RuntimeEvent {
  event_type: string;
  payload: string | null;
  fired_at: number;
}

export interface SessionDetail extends SessionSummary {
  file_touches: FileTouch[];
  risky_commands: RiskyCommand[];
  outcome_signals: OutcomeSignal[];
  anomalies: Anomaly[];
  runtime_events: RuntimeEvent[];
  checkpoint_fired: boolean;
  runtime_warning_count: number;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface DiffResponse {
  session_id: string;
  diff: string;
  available: boolean;
}

export interface PatchSessionRequest {
  manual_outcome?: "success" | "partial" | "abandoned" | null;
  note?: string | null;
  perceived_quality?: number | null;
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listSessions(limit = 50, offset = 0): Promise<SessionListResponse> {
    return request(`/sessions?limit=${limit}&offset=${offset}`);
  },

  getSession(id: string): Promise<SessionDetail> {
    return request(`/sessions/${id}`);
  },

  getDiff(id: string): Promise<DiffResponse> {
    return request(`/sessions/${id}/diff`);
  },

  patchSession(id: string, body: PatchSessionRequest): Promise<SessionDetail> {
    return request(`/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },
};
