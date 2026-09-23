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
import { elapsed, formatWhen, SEVERITY_LABEL, STATUS_LABEL } from "./format";

const NOTE_KINDS: { value: EvidenceKind; label: string }[] = [
  { value: "symptom", label: "Symptom" },
  { value: "log", label: "Log line" },
  { value: "timeline", label: "Timeline" },
  { value: "change", label: "Change" },
  { value: "hypothesis", label: "Hypothesis" },
];

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
      <main>
        <p className="quiet">Loading the case.</p>
      </main>
    );
  }

  if (!detail) {
    return (
      <main>
        <p className="problem">{error}</p>
        <Link to="/">All cases</Link>
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

  const live = detail.status === "open" || detail.status === "investigating";

  return (
    <main className="sheet">
      <p className="back">
        <Link to="/">All cases</Link>
      </p>
      <header className="case-head">
        <div>
          <h1>{detail.title}</h1>
          <p className="service">{detail.service}</p>
        </div>
        <p className="severity-line">
          <span className={`lamp ${detail.severity} ${live ? "live" : ""}`} aria-hidden="true" />
          {SEVERITY_LABEL[detail.severity]}
          <span className="gap" />
          {STATUS_LABEL[detail.status]}
        </p>
      </header>
      <p className="when">
        Started {formatWhen(detail.started_at)}
        <span className="gap" />
        {elapsed(detail.started_at, now)}
        {detail.opened_by ? (
          <>
            <span className="gap" />
            Opened by {detail.opened_by}
          </>
        ) : null}
      </p>
      <p className="summary">{detail.summary}</p>
      <div className="actions">
        <button type="button" onClick={onInvestigate} disabled={busy || running || detail.status === "resolved"}>
          {running ? "Investigation running" : "Investigate"}
        </button>
        <button type="button" className="quiet-button" onClick={() => mark("mitigated")} disabled={busy || detail.status === "mitigated"}>
          Mark mitigated
        </button>
        <button type="button" className="quiet-button" onClick={() => mark("resolved")} disabled={busy || detail.status === "resolved"}>
          Mark resolved
        </button>
      </div>
      {error ? <p className="problem">{error}</p> : null}
      <div className="sheet-grid">
        <section>
          <h2>Timeline</h2>
          <EvidenceList items={timeline} empty="Nothing on the timeline yet. Investigate, or add a note." />
        </section>
        <div className="side">
          <section>
            <h2>Hypotheses</h2>
            <EvidenceList items={hypotheses} empty="No hypothesis recorded yet." />
          </section>
          <section>
            <h2>Log lines</h2>
            <EvidenceList items={logs} empty="No log lines recorded yet." />
          </section>
        </div>
      </div>
      <section className="note">
        <h2>Incident note</h2>
        {latest?.provider ? (
          <p className="quiet">
            This run used {latest.provider} {latest.model_name} and is {latest.status}.
          </p>
        ) : (
          <p className="quiet">No investigation yet.</p>
        )}
        {latest?.error ? <p className="problem">{latest.error}</p> : null}
        {latest?.report ? <div className="report">{latest.report}</div> : null}
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

function EvidenceList({ items, empty }: { items: Evidence[]; empty: string }) {
  if (items.length === 0) {
    return <p className="quiet">{empty}</p>;
  }
  return (
    <ol className="timeline">
      {items.map((item) => (
        <li key={item.id}>
          <time dateTime={item.recorded_at}>{formatWhen(item.recorded_at)}</time>
          <p>{item.summary}</p>
          <p className="quiet">{item.source}</p>
        </li>
      ))}
    </ol>
  );
}
