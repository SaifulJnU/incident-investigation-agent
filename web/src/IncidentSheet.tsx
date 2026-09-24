import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  addNote,
  getIncident,
  investigate,
  updateIncident,
  type CaseStatus,
  type Evidence,
  type EvidenceKind,
  type IncidentDetail,
} from "./api";
import { elapsed, formatWhen, timeTaken, SEVERITY_LABEL, STATUS_LABEL } from "./format";

function who(name: string, subject: string): string {
  return name || subject;
}

const NOTE_KINDS: { value: EvidenceKind; label: string }[] = [
  { value: "symptom", label: "Symptom" },
  { value: "log", label: "Log line" },
  { value: "timeline", label: "Timeline" },
  { value: "change", label: "Change" },
  { value: "hypothesis", label: "Hypothesis" },
];

const KIND_LABEL: Record<EvidenceKind, string> = {
  symptom: "Symptom",
  log: "Log line",
  timeline: "Timeline",
  change: "Change",
  hypothesis: "Hypothesis",
};

export function IncidentSheet() {
  const { id = "" } = useParams();
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [kind, setKind] = useState<EvidenceKind>("log");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let gone = false;
    getIncident(id)
      .then((next) => {
        if (!gone) {
          setDetail(next);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!gone) {
          setError(err instanceof Error ? err.message : "Could not load this case.");
        }
      });
    return () => {
      gone = true;
    };
  }, [id]);

  useEffect(() => {
    const active = detail?.runs.some((run) => run.status === "queued" || run.status === "running");
    if (!active) {
      return;
    }
    const timer = window.setTimeout(() => {
      getIncident(id)
        .then((next) => setDetail(next))
        .catch(() => undefined);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [id, detail]);

  if (!detail && !error) {
    return (
      <main className="sheet sheet-loading">
        <p className="quiet">Loading the case.</p>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="sheet">
        <p className="back">
          <Link to="/">All cases</Link>
        </p>
        <p className="problem" role="alert">
          {error}
        </p>
      </main>
    );
  }

  const latest = detail.runs[0];
  const running = detail.runs.some((run) => run.status === "queued" || run.status === "running");
  const timeline = detail.evidence.filter((item) => item.kind === "symptom" || item.kind === "timeline" || item.kind === "change");
  const hypotheses = detail.evidence.filter((item) => item.kind === "hypothesis");
  const logs = detail.evidence.filter((item) => item.kind === "log");

  async function refresh() {
    setDetail(await getIncident(id));
  }

  async function onInvestigate() {
    setBusy(true);
    setError(null);
    try {
      await investigate(id);
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not start the investigation.");
    } finally {
      setBusy(false);
    }
  }

  async function mark(status: CaseStatus) {
    setBusy(true);
    setError(null);
    try {
      await updateIncident(id, { status });
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not update the case.");
    } finally {
      setBusy(false);
    }
  }

  async function onNote(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setDetail(await addNote(id, kind, note));
      setNote("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not add the note.");
    } finally {
      setBusy(false);
    }
  }

  const taken = latest ? timeTaken(latest.started_at, latest.finished_at) : "";
  const live = detail.status === "open" || detail.status === "investigating";
  const age = elapsed(detail.started_at, now);
  const opener = who(detail.opened_by_name, detail.opened_by);
  const mitigator = who(detail.mitigated_by_name, detail.mitigated_by);
  const resolver = who(detail.resolved_by_name, detail.resolved_by);

  return (
    <main className="sheet">
      <p className="back">
        <Link to="/">All cases</Link>
      </p>
      <header className="case-head">
        <span className={`rail ${detail.severity} ${live ? "live" : ""}`} aria-hidden="true" />
        <div className="head-copy">
          <h1>{detail.title}</h1>
          <p className="service">{detail.service}</p>
          <p className="head-status">
            <span className={`chip ${detail.severity}`}>{SEVERITY_LABEL[detail.severity]}</span>
            <span className={`chip ${detail.status}`}>{STATUS_LABEL[detail.status]}</span>
          </p>
        </div>
      </header>
      <dl className="facts">
        <div>
          <dt>Started</dt>
          <dd>{formatWhen(detail.started_at)}</dd>
        </div>
        {age ? (
          <div>
            <dt>Age</dt>
            <dd>{age}</dd>
          </div>
        ) : null}
        {opener ? (
          <div>
            <dt>Opened by</dt>
            <dd>{opener}</dd>
          </div>
        ) : null}
        {mitigator ? (
          <div>
            <dt>Mitigated by</dt>
            <dd>{mitigator}</dd>
          </div>
        ) : null}
        {resolver ? (
          <div>
            <dt>Resolved by</dt>
            <dd>{resolver}</dd>
          </div>
        ) : null}
      </dl>
      <p className="summary">{detail.summary}</p>
      <div className="actions">
        <button type="button" onClick={onInvestigate} disabled={busy || running || detail.status === "resolved"}>
          {running ? "Investigation running" : "Investigate"}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => mark("mitigated")}
          disabled={busy || detail.status === "mitigated"}
        >
          Mark mitigated
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => mark("resolved")}
          disabled={busy || detail.status === "resolved"}
        >
          Mark resolved
        </button>
      </div>
      {error ? (
        <p className="problem" role="alert">
          {error}
        </p>
      ) : null}
      <div className="sheet-grid">
        <section>
          <h2>Timeline</h2>
          <EvidenceList items={timeline} empty="Nothing on the timeline yet. Investigate, or add a note." showKind />
        </section>
        <div className="side">
          <section>
            <h2>Hypotheses</h2>
            <EvidenceList items={hypotheses} empty="No hypothesis recorded yet." />
          </section>
          <section>
            <h2>Log lines</h2>
            <EvidenceList items={logs} empty="No log lines recorded yet." mono />
          </section>
        </div>
      </div>
      <section className="brief">
        <h2>Incident note</h2>
        {latest?.provider ? (
          <p className="quiet">
            This run used {latest.provider} {latest.model_name} and is {latest.status}.
          </p>
        ) : (
          <p className="quiet">No investigation yet.</p>
        )}
        {latest?.error ? (
          <p className="problem" role="alert">
            {latest.error}
          </p>
        ) : null}
        {latest?.report ? <div className="report">{latest.report}</div> : null}
        {taken ? <p className="taken">Time taken: {taken}</p> : null}
      </section>
      <form onSubmit={onNote} className="intake note-form">
        <h2>Add a note</h2>
        <label>
          Kind
          <select value={kind} onChange={(event) => setKind(event.target.value as EvidenceKind)}>
            {NOTE_KINDS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Note
          <textarea value={note} onChange={(event) => setNote(event.target.value)} required rows={3} />
        </label>
        <button type="submit" disabled={busy}>
          Add note
        </button>
      </form>
    </main>
  );
}

function EvidenceList({
  items,
  empty,
  showKind = false,
  mono = false,
}: {
  items: Evidence[];
  empty: string;
  showKind?: boolean;
  mono?: boolean;
}) {
  if (items.length === 0) {
    return <p className="quiet">{empty}</p>;
  }
  return (
    <ol className="timeline">
      {items.map((item) => (
        <li key={item.id}>
          {showKind ? <span className="kind">{KIND_LABEL[item.kind]}</span> : null}
          <time dateTime={item.recorded_at}>{formatWhen(item.recorded_at)}</time>
          <p className={mono ? "log-body" : undefined}>{item.summary}</p>
          <p className="quiet">{item.source}</p>
        </li>
      ))}
    </ol>
  );
}
