export type Severity = "sev1" | "sev2" | "sev3" | "sev4";
export type CaseStatus = "open" | "investigating" | "mitigated" | "resolved";
export type EvidenceKind = "symptom" | "log" | "timeline" | "change" | "hypothesis";
export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface Incident {
  id: string;
  title: string;
  summary: string;
  service: string;
  severity: Severity;
  status: CaseStatus;
  started_at: string;
  created_at: string;
  updated_at: string;
}

export interface Evidence {
  id: string;
  kind: EvidenceKind;
  summary: string;
  source: string;
  recorded_at: string;
}

export interface Run {
  id: string;
  status: RunStatus;
  provider: string;
  model_name: string;
  report: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface IncidentDetail extends Incident {
  evidence: Evidence[];
  runs: Run[];
}

export interface NewCase {
  title: string;
  service: string;
  summary: string;
  severity: Severity;
  started_at?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      detail = "The case file API is not responding.";
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function listIncidents(): Promise<Incident[]> {
  return request("/api/incidents");
}

export function getIncident(id: string): Promise<IncidentDetail> {
  return request(`/api/incidents/${id}`);
}

export function createIncident(body: NewCase): Promise<Incident> {
  return request("/api/incidents", { method: "POST", body: JSON.stringify(body) });
}

export function updateIncident(
  id: string,
  body: { status?: CaseStatus; severity?: Severity; summary?: string },
): Promise<Incident> {
  return request(`/api/incidents/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function addNote(id: string, kind: EvidenceKind, summary: string): Promise<IncidentDetail> {
  return request(`/api/incidents/${id}/evidence`, {
    method: "POST",
    body: JSON.stringify({ kind, summary }),
  });
}

export function investigate(id: string): Promise<Run> {
  return request(`/api/incidents/${id}/investigate`, { method: "POST" });
}
