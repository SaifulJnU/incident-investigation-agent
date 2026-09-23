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
  opened_by: string;
  opened_by_name: string;
  mitigated_by: string;
  mitigated_by_name: string;
  mitigated_at: string | null;
  resolved_by: string;
  resolved_by_name: string;
  resolved_at: string | null;
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
  requested_by: string;
  requested_by_name: string;
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

const TOKEN_KEY = "case-file.token";

let onUnauthorized: () => void = () => undefined;

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

export function readToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function storeToken(token: string) {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = readToken();
  const response = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (response.status === 401 && token) {
    clearToken();
    onUnauthorized();
  }
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

export function listIncidents(status?: CaseStatus): Promise<Incident[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request(`/api/incidents${query}`);
}

export function incidentCounts(): Promise<Record<CaseStatus | "all", number>> {
  return request("/api/incidents/counts");
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

export interface AuthConfig {
  mode: "dev" | "oidc";
  issuer?: string;
  client_id?: string;
  audience?: string;
  authorization_endpoint?: string;
  token_endpoint?: string;
}

export interface Caller {
  subject: string;
  name: string;
  services: string[];
  allows_all: boolean;
}

export function authConfig(): Promise<AuthConfig> {
  return request("/api/auth/config");
}

export function devSignIn(subject: string, password: string): Promise<{ access_token: string }> {
  return request("/api/auth/dev/token", {
    method: "POST",
    body: JSON.stringify({ subject, password }),
  });
}

export function currentCaller(): Promise<Caller> {
  return request("/api/auth/me");
}
