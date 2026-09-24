import type { CaseStatus, Severity } from "./api";

export const SEVERITY_LABEL: Record<Severity, string> = {
  sev1: "Sev-1",
  sev2: "Sev-2",
  sev3: "Sev-3",
  sev4: "Sev-4",
};

export const STATUS_LABEL: Record<CaseStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  mitigated: "Mitigated",
  resolved: "Resolved",
};

export function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  const formatted = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hourCycle: "h23",
  }).format(date);
  return `${formatted} UTC`;
}

export function timeTaken(startedIso: string | null, finishedIso: string | null): string {
  if (!startedIso || !finishedIso) {
    return "";
  }
  const started = new Date(startedIso).getTime();
  const finished = new Date(finishedIso).getTime();
  if (Number.isNaN(started) || Number.isNaN(finished) || finished < started) {
    return "";
  }
  const totalSeconds = Math.round((finished - started) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

export function elapsed(iso: string, now = Date.now()): string {
  const start = new Date(iso).getTime();
  if (Number.isNaN(start)) {
    return "";
  }
  const minutes = Math.max(0, Math.floor((now - start) / 60000));
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `${hours}h ${minutes % 60}m`;
  }
  return `${Math.floor(hours / 24)}d`;
}
