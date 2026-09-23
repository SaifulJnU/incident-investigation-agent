import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createIncident, listIncidents, type Incident, type Severity } from "./api";
import { elapsed, formatWhen, SEVERITY_LABEL, STATUS_LABEL } from "./format";

const SAMPLE = {
  title: "Checkout errors after the payments deploy",
  service: "checkout-api",
  severity: "sev1" as Severity,
  summary:
    "HTTP 500s on POST /checkout climbed after payments-api 1.42.0 deployed at 14:02 UTC. Catalog still looks healthy. No database failover was announced.",
  started_at: "2026-09-22T14:02:00Z",
};

export function IncidentList() {
  const navigate = useNavigate();
  const [cases, setCases] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [title, setTitle] = useState("");
  const [service, setService] = useState("");
  const [summary, setSummary] = useState("");
  const [severity, setSeverity] = useState<Severity>("sev2");
  const [startedAt, setStartedAt] = useState("");

  useEffect(() => {
    let gone = false;
    listIncidents()
      .then((rows) => {
        if (!gone) {
          setCases(rows);
        }
      })
      .catch((err: unknown) => {
        if (!gone) {
          setError(err instanceof Error ? err.message : "Could not load cases.");
        }
      })
      .finally(() => {
        if (!gone) {
          setLoading(false);
        }
      });
    return () => {
      gone = true;
    };
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await createIncident({
        title,
        service,
        summary,
        severity,
        started_at: startedAt.trim() || undefined,
      });
      navigate(`/incidents/${created.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not open the case.");
      setSaving(false);
    }
  }

  function useSample() {
    setTitle(SAMPLE.title);
    setService(SAMPLE.service);
    setSummary(SAMPLE.summary);
    setSeverity(SAMPLE.severity);
    setStartedAt(SAMPLE.started_at);
  }

  return (
    <main className="desk">
      <section>
        <h1>Open a case</h1>
        <form onSubmit={onSubmit} className="intake">
          <label>
            Title
            <input value={title} onChange={(event) => setTitle(event.target.value)} required />
          </label>
          <label>
            Service
            <input value={service} onChange={(event) => setService(event.target.value)} required />
          </label>
          <label>
            Severity
            <select value={severity} onChange={(event) => setSeverity(event.target.value as Severity)}>
              {(Object.keys(SEVERITY_LABEL) as Severity[]).map((level) => (
                <option key={level} value={level}>
                  {SEVERITY_LABEL[level]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Started (UTC)
            <input
              value={startedAt}
              onChange={(event) => setStartedAt(event.target.value)}
              placeholder="2026-09-22T14:02:00Z"
            />
          </label>
          <label>
            What happened
            <textarea value={summary} onChange={(event) => setSummary(event.target.value)} required rows={5} />
          </label>
          <div className="actions">
            <button type="submit" disabled={saving}>
              {saving ? "Opening" : "Open case"}
            </button>
            <button type="button" className="quiet-button" onClick={useSample}>
              Use the checkout sample
            </button>
          </div>
        </form>
        {error ? <p className="problem">{error}</p> : null}
      </section>
      <section>
        <h2>Cases</h2>
        {loading ? <p className="quiet">Loading cases.</p> : null}
        {!loading && cases.length === 0 ? (
          <p className="quiet">No cases yet. Open one from the form, or start from the checkout sample.</p>
        ) : null}
        <ul className="case-list">
          {cases.map((item) => (
            <li key={item.id}>
              <Link to={`/incidents/${item.id}`} className="case-row">
                <span
                  className={`lamp ${item.severity} ${item.status === "open" || item.status === "investigating" ? "live" : ""}`}
                  aria-hidden="true"
                />
                <span className="case-title">{item.title}</span>
                <span className="case-meta">
                  {SEVERITY_LABEL[item.severity]}
                  <span className="gap" />
                  {item.service}
                  <span className="gap" />
                  {STATUS_LABEL[item.status]}
                  <span className="gap" />
                  {formatWhen(item.started_at)}
                  <span className="gap" />
                  {elapsed(item.started_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
