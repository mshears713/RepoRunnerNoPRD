const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

export type ScanStatus = "pending" | "running" | "completed" | "failed";

export interface ScanTimeline {
  forked_at?: string;
  codespace_ready_at?: string;
  started_at?: string;
  finished_at?: string;
}

export interface ScanExecution {
  stage_reached: "cloned" | "installed" | "started";
  port?: number;
  health_check_url?: string;
  stdout_tail: string;
  stderr_tail: string;
  exit_code: number;
  duration_sec: number;
}

export interface ScanAnalysis {
  what_it_does: string;
  use_case: string;
  tech_stack: string[];
  caveats: string[];
}

export interface ScanFailure {
  category: string;
  plain_explanation: string;
  fix_suggestions: string[];
}

export interface Scan {
  id: string;
  created_at: string;
  updated_at: string;
  status: ScanStatus;
  repo_url: string;
  repo_owner: string;
  repo_name: string;
  input_metadata: {
    summary?: string;
    reason_selected?: string;
    tags?: string[];
    priority?: string;
  };
  fork_repo_name?: string;
  codespace_name?: string;
  preview_url?: string;
  accessible?: boolean;
  timeline: ScanTimeline;
  execution?: ScanExecution;
  analysis?: ScanAnalysis;
  failure?: ScanFailure;
  cleanup: {
    codespace_deleted: boolean;
    fork_deleted: boolean;
  };
}

export interface ScanListResponse {
  items: Scan[];
  total: number;
}

export interface SubmitRequest {
  repo_url: string;
  summary?: string;
  reason_selected?: string;
  tags?: string[];
  priority?: string;
}

// ------------------------------------------------------------------
// API functions
// ------------------------------------------------------------------

export async function submitScan(body: SubmitRequest): Promise<{ id: string; status: string; created_at: string }> {
  const res = await fetch(`${API_BASE}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function listScans(status?: string, limit = 50, offset = 0): Promise<ScanListResponse> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const res = await fetch(`${API_BASE}/api/scan?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function getScan(id: string): Promise<Scan> {
  const res = await fetch(`${API_BASE}/api/scan/${id}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function deleteScan(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/scan/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export function getScanStreamUrl(id: string): string {
  return `${API_BASE}/api/scan/${id}/stream`;
}
