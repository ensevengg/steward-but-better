"use client";
import { useEffect, useState } from "react";
import type { Case, Dashboard } from "./types/incident";
import EvidenceTimeline from "./components/EvidenceTimeline";

const labels: Record<string, string> = {
  PENALTY_RECOMMENDED: "Penalty recommended",
  NO_FURTHER_ACTION: "No further action",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
  REVIEW_REQUIRED: "Review required",
};
const words = (text: string) => text.replaceAll("_", " ");
const display = (n: number | null | undefined, digits = 1) =>
  n == null ? "—" : n.toFixed(digits);
async function readResponse(response: Response) {
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : (body.error ?? "Request failed. Please retry."),
    );
  return body;
}

export default function Home() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [session, setSession] = useState("");
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Case | null>(null);
  const [filter, setFilter] = useState("open");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [now, setNow] = useState(0);
  const [tab, setTab] = useState<"timing" | "cases">("cases");
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const data: Dashboard = await fetch(
          `/api/telemetry${session ? `?session_id=${encodeURIComponent(session)}` : ""}`,
          { cache: "no-store", signal: controller.signal },
        ).then(readResponse);
        if (!controller.signal.aborted) {
          setDashboard(data);
          setSelected((id) =>
            data.investigations.some((item) => item.id === id) ? id : "",
          );
          setError("");
          setNow(Date.now());
        }
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Connection lost");
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 1500);
      }
    }
    refresh();
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      controller.abort();
      clearTimeout(timer);
      clearInterval(clock);
    };
  }, [session, revision]);
  const version = dashboard?.investigations.find(
    (c) => c.id === selected,
  )?.version;
  const processing = dashboard?.investigations.find(
    (c) => c.id === selected,
  )?.processing_state;
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    fetch(`/api/investigations/${encodeURIComponent(selected)}`, {
      signal: controller.signal,
    })
      .then(readResponse)
      .then((data) => {
        if (!controller.signal.aborted) setDetail(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setActionError(e.message);
      });
    return () => controller.abort();
  }, [selected, version, processing, revision]);
  const current = detail?.id === selected ? detail : null;
  const age = dashboard?.live
    ? Math.max(0, (now - Date.parse(dashboard.live.received_at)) / 1000)
    : null;
  const finished = dashboard?.live?.status === "FINISHED";
  const stale = !!error || (age !== null && age > 5 && !finished);
  const cases = dashboard?.investigations ?? [];
  const visibleCases = cases.filter(
    (c) => filter === "all" || c.workflow === filter,
  );
  const openCount = cases.filter((c) => c.workflow === "open").length;
  async function loadStudy() {
    setBusy(true);
    setActionError("");
    try {
      const result = await fetch("/api/studies/sao-paulo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }).then(readResponse);
      setSession(result.session_id);
      setSelected(result.case_id);
      setFilter("open");
      setTab("cases");
      setRevision((n) => n + 1);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Unable to load study");
    } finally {
      setBusy(false);
    }
  }
  async function changeWorkflow() {
    if (!current) return;
    setBusy(true);
    setActionError("");
    try {
      const updated = await fetch(
        `/api/investigations/${encodeURIComponent(current.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: current.workflow === "open" ? "closed" : "open",
            expected_version: current.version,
          }),
        },
      ).then(readResponse);
      setDetail(updated);
      setRevision((n) => n + 1);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Unable to update case");
      setRevision((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="workspace">
      <a className="skip-link" href="#main">
        Skip to race control
      </a>
      <header className="topbar">
        <div>
          <p className="eyebrow">Steward / Race control</p>
          <h1>Evidence before judgment.</h1>
          <p className="muted">
            Review the incident. Understand the uncertainty.
          </p>
        </div>
        <button className="button" disabled={busy} onClick={loadStudy}>
          {busy ? "Working…" : "Load São Paulo 2025 study"}
        </button>
      </header>
      <div className="sessionbar">
        <label>
          Session{" "}
          <select
            aria-label="Session"
            value={session}
            onChange={(e) => {
              setSession(e.target.value);
              setSelected("");
            }}
          >
            <option value="">Latest session</option>
            {dashboard?.sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <div className="feed-status" aria-live="polite">
          <span className={`status-dot ${stale ? "stale" : ""}`} />
          {!dashboard?.live
            ? "Waiting for telemetry"
            : finished
              ? "Replay complete"
              : stale
                ? "Feed stale"
                : dashboard.live.status === "REPLAY"
                  ? "Historical replay"
                  : "Live feed"}
        </div>
        <span className="muted">
          {age === null
            ? "No samples received"
            : `Last packet ${Math.floor(age)}s ago`}{" "}
          · {openCount} open cases
        </span>
      </div>
      {error && (
        <p className="notice" role="status">
          {error} Last received values may be stale.
        </p>
      )}
      {actionError && (
        <p className="notice" role="alert">
          {actionError}
        </p>
      )}
      <main id="main">
        <nav className="mobile-tabs" aria-label="Workspace view">
          <button
            aria-pressed={tab === "cases"}
            onClick={() => setTab("cases")}
          >
            Cases
          </button>
          <button
            aria-pressed={tab === "timing"}
            onClick={() => setTab("timing")}
          >
            Timing
          </button>
        </nav>
        <div className="workspace-grid">
          <section
            className={`panel timing ${tab === "timing" ? "mobile-active" : ""}`}
            aria-labelledby="timing-title"
          >
            <div className="panel-heading">
              <h2 id="timing-title">Timing</h2>
              <span className="muted">
                {dashboard?.live?.all_drivers.length ?? 0} drivers
              </span>
            </div>
            <p className="session-name">
              {dashboard?.live?.session_name ?? "Connect a replay to begin"}
            </p>
            {dashboard?.live?.all_drivers.length ? (
              <table className="timing-table">
                <caption className="sr-only">
                  Latest driver telemetry. Missing values are shown as a dash.
                </caption>
                <thead>
                  <tr>
                    <th>Driver</th>
                    <th>km/h</th>
                    <th>Lap</th>
                    <th>Gap</th>
                  </tr>
                </thead>
                <tbody>
                  {dashboard.live.all_drivers.map((d) => (
                    <tr key={d.driver_code}>
                      <th scope="row">
                        {d.driver_code}
                        <small>
                          {d.status === "UNKNOWN"
                            ? "Unconfirmed"
                            : d.status === "OUT"
                              ? "Out"
                              : ""}
                        </small>
                      </th>
                      <td>{display(d.current_speed)}</td>
                      <td>{d.lap_number ?? "—"}</td>
                      <td>{display(d.delta_to_leader, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="empty">
                Telemetry appears here when a session starts. The study loads
                recorded FastF1 samples.
              </p>
            )}
            <p className="footnote">
              Public telemetry estimates cannot establish precise racing lines
              or blame. Unavailable values remain unknown.
            </p>
          </section>
          <section
            className={`panel case-list ${tab === "cases" ? "mobile-active" : ""}`}
            aria-labelledby="cases-title"
          >
            <div className="panel-heading">
              <h2 id="cases-title">Cases</h2>
              <label className="sr-only" htmlFor="case-filter">
                Case filter
              </label>
              <select
                id="case-filter"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="open">Open</option>
                <option value="closed">Closed</option>
                <option value="all">All history</option>
              </select>
            </div>
            <div className="case-scroll" data-testid="case-list">
              {visibleCases.length ? (
                visibleCases.map((c) => (
                  <button
                    key={c.id}
                    className={`case-item ${selected === c.id ? "selected" : ""}`}
                    onClick={() => {
                      setSelected(c.id);
                      setActionError("");
                    }}
                    aria-pressed={selected === c.id}
                  >
                    <span className="case-meta">
                      Lap {c.lap} · {c.corner}
                    </span>
                    <strong>
                      {c.driver}
                      {c.rival ? ` / ${c.rival}` : ""}
                    </strong>
                    <span>{c.title}</span>
                    <span className={`badge ${c.ruling ?? ""}`}>
                      {c.processing_state === "failed"
                        ? "Assessment failed · review needed"
                        : c.ruling
                          ? labels[c.ruling]
                          : `${words(c.processing_state)}…`}
                    </span>
                    <small>
                      {words(c.evidence_mode)} · {c.workflow}
                    </small>
                  </button>
                ))
              ) : (
                <p className="empty">
                  No cases in this view. Case history is retained after replay
                  and closure.
                </p>
              )}
            </div>
          </section>
          <section
            className={`panel evidence ${tab === "cases" ? "mobile-active" : ""}`}
            aria-labelledby="evidence-title"
          >
            <div className="panel-heading">
              <h2 id="evidence-title">Evidence review</h2>
              {current && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={changeWorkflow}
                >
                  {current.workflow === "open" ? "Close case" : "Reopen case"}
                </button>
              )}
            </div>
            {!selected ? (
              <div className="empty evidence-empty">
                <h3>Select a case</h3>
                <p>
                  Compare observations, rule conditions and alternative
                  explanations before accepting a recommendation.
                </p>
                <p>Closing a case changes its workflow, not its judgment.</p>
              </div>
            ) : !current ? (
              <p className="empty" role="status">
                Loading case evidence…
              </p>
            ) : (
              <>
                <div className="case-intro">
                  <p className="eyebrow">
                    {current.event_date} · Lap {current.lap} · {current.corner}
                  </p>
                  <h3>{current.title}</h3>
                  <p className={`badge ${current.ruling ?? ""}`}>
                    {current.ruling
                      ? labels[current.ruling]
                      : words(current.processing_state)}
                    {current.penalty_seconds != null
                      ? ` · ${current.penalty_seconds} seconds`
                      : ""}
                  </p>
                  <p>
                    {current.summary ?? "Waiting for the evidence assessment."}
                  </p>
                </div>
                {current.evidence_mode === "document_reconstruction" && (
                  <p className="notice neutral">
                    Document reconstruction: observations are annotated from the
                    FIA’s published account. This checks rule application, not
                    independent video perception or blind historical accuracy.
                  </p>
                )}
                {current.evidence_mode === "telemetry_only" && (
                  <p className="notice neutral">
                    Telemetry only: overlap, contact and responsibility require
                    additional evidence.
                  </p>
                )}
                <EvidenceTimeline samples={current.samples ?? []} />
                <section className="detail-section">
                  <h4>Rule conditions</h4>
                  {current.conditions?.length ? (
                    <ul className="conditions">
                      {current.conditions.map((c) => (
                        <li key={c.predicate}>
                          <span>{words(c.predicate)}</span>
                          <span className={`condition-status ${c.status}`}>
                            {c.status}
                          </span>
                          <small>
                            {c.evidence_ids.join(", ") ||
                              "No qualifying evidence"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">
                      No supported rule pattern is available for this case.
                    </p>
                  )}
                </section>
                <section className="detail-section">
                  <h4>Alternative explanation</h4>
                  <p>
                    {current.alternative_explanation ?? "Assessment pending."}
                  </p>
                  {!!current.missing_facts?.length && (
                    <p className="muted">
                      Still needed:{" "}
                      {current.missing_facts.map(words).join("; ")}.
                    </p>
                  )}
                </section>
                <section className="detail-section">
                  <h4>Observations & provenance</h4>
                  {current.observations?.length ? (
                    current.observations.map((e) => (
                      <div key={e.id} className="observation">
                        <strong>
                          {e.id} · {words(e.predicate)}:{" "}
                          {e.value ? "yes" : "no"}
                        </strong>
                        <p>{e.detail}</p>
                        <small>
                          {e.verified ? "Reviewed annotation" : "Unverified"} ·{" "}
                          {words(e.source)}
                        </small>
                        {e.source_ref.startsWith("https://") ? (
                          <a
                            href={e.source_ref}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open evidence source ↗
                          </a>
                        ) : (
                          <small>{e.source_ref}</small>
                        )}
                      </div>
                    ))
                  ) : (
                    <p className="muted">
                      No reviewed spatial observations supplied.
                    </p>
                  )}
                </section>
                <section className="detail-section">
                  <h4>Applicable rules</h4>
                  {current.rules?.map((r) => (
                    <details key={r.id}>
                      <summary>{r.title}</summary>
                      <p>{r.text}</p>
                      <a
                        href={`${r.url}#page=${r.page}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Source document · page {r.page} ↗
                      </a>
                      <p className="footnote">
                        Reviewed synopsis · {words(r.authority)}
                      </p>
                    </details>
                  ))}
                  {!current.rules?.length && (
                    <p className="muted">
                      No reviewed rules apply. Another season’s rules will not
                      be substituted.
                    </p>
                  )}
                </section>
                <section className="detail-section">
                  <h4>Model review</h4>
                  <p>
                    {words(current.model_review?.status ?? "pending")}
                    {current.model_review?.model
                      ? ` · ${current.model_review.model}`
                      : ""}
                  </p>
                  {current.model_review?.summary && (
                    <p>{current.model_review.summary}</p>
                  )}
                  {current.model_review?.alternative_explanation && (
                    <p>{current.model_review.alternative_explanation}</p>
                  )}
                  <p className="footnote">
                    No calibrated probability is available. Penalty points
                    require separate review.
                  </p>
                </section>
                {!!current.limitations?.length && (
                  <section className="detail-section">
                    <h4>Evidence limitations</h4>
                    <ul>
                      {current.limitations.map((l) => (
                        <li key={l}>{l}</li>
                      ))}
                    </ul>
                  </section>
                )}
                <details className="detail-section">
                  <summary>Case history</summary>
                  <ul>
                    {current.audit?.map((a, i) => (
                      <li key={i}>
                        {words(a.action)} ·{" "}
                        {new Date(a.timestamp).toLocaleString()}
                      </li>
                    ))}
                  </ul>
                </details>
              </>
            )}
          </section>
        </div>
      </main>
      <footer>
        Steward · Evidence-backed recommendations, with uncertainty preserved.
      </footer>
    </div>
  );
}
