"use client";
import { useEffect, useState, type CSSProperties } from "react";
import type { Case, Dashboard, Driver } from "./types/incident";
import CaseReview, { rulingLabels } from "./components/CaseReview";

const value = (n: number | null | undefined, digits = 0) =>
  n == null ? "—" : n.toFixed(digits);
const clock = (n: number) =>
  `${Math.floor(n / 3600)
    .toString()
    .padStart(2, "0")}:${Math.floor((n / 60) % 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(n % 60)
    .toString()
    .padStart(2, "0")}`;
async function read(response: Response) {
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : (body.error ?? "Request failed"),
    );
  return body;
}

function DriverCard({
  driver: d,
  stale,
  reports,
  selected,
  onSelect,
}: {
  driver: Driver;
  stale: boolean;
  reports: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const missing = stale || d.status === "UNKNOWN";
  return (
    <article
      className={`driver-card ${selected ? "selected" : ""} ${missing ? "is-stale" : ""}`}
      data-testid="driver-card"
      data-driver={d.driver_code}
      style={
        {
          "--team": d.team_color ? `#${d.team_color}` : "#65717b",
        } as CSSProperties
      }
    >
      <div className="driver-top">
        <button
          className="driver-name"
          onClick={onSelect}
          aria-label={`Show reports for ${d.driver_code}`}
          aria-pressed={selected}
        >
          {d.driver_code}
        </button>
        <span
          className="position"
          title={d.timing_source ?? "Position unavailable"}
        >
          {d.position_rank ? `P${d.position_rank}` : "P —"}
        </span>
      </div>
      <div className="driver-team">
        {d.team ||
          (d.driver_number ? `Car ${d.driver_number}` : "Team unavailable")}
        <span>
          {d.status === "PIT"
            ? "PIT"
            : d.status === "OUT"
              ? "OUT"
              : missing
                ? "STALE"
                : ""}
        </span>
      </div>
      <div className="speed-line">
        <strong data-testid="speed">{value(d.current_speed)}</strong>
        <span>km/h</span>
        <div>
          <small>GEAR</small>
          <b>{value(d.gear)}</b>
        </div>
      </div>
      <div className="driver-metrics">
        <span>
          <small>LAP</small>
          {value(d.lap_number)}
        </span>
        <span title={d.timing_source ?? "Timing source unavailable"}>
          <small>GAP</small>
          {d.gap_text ??
            (d.delta_to_leader == null
              ? "—"
              : `+${d.delta_to_leader.toFixed(1)}`)}
        </span>
        <span>
          <small>RPM</small>
          {d.rpm == null ? "—" : `${(d.rpm / 1000).toFixed(1)}k`}
        </span>
      </div>
      <div className="pedals">
        <div
          className="throttle"
          aria-label={`Throttle ${d.throttle == null ? "unknown" : `${d.throttle} percent`}`}
        >
          <i style={{ width: `${d.throttle ?? 0}%` }} />
        </div>
        <span className={d.brake_applied ? "braking" : ""}>
          {d.brake_applied == null
            ? "BRK —"
            : d.brake_applied
              ? "BRAKE"
              : "BRK"}
        </span>
        <span className="report-count">
          {reports ? `${reports} flag${reports > 1 ? "s" : ""}` : ""}
        </span>
      </div>
    </article>
  );
}

export default function Home() {
  const [state, setState] = useState<Dashboard | null>(null);
  const [session, setSession] = useState("");
  const [selected, setSelected] = useState("");
  const [driver, setDriver] = useState("");
  const [detail, setDetail] = useState<Case | null>(null);
  const [filter, setFilter] = useState("open");
  const [railTab, setRailTab] = useState("reports");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [now, setNow] = useState(0);
  const [mobileTab, setMobileTab] = useState("field");
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const next: Dashboard = await fetch(
          `/api/telemetry${session ? `?session_id=${encodeURIComponent(session)}` : ""}`,
          { cache: "no-store", signal: abort.signal },
        ).then(read);
        if (!abort.signal.aborted) {
          setState(next);
          setError("");
          setSelected((id) =>
            next.investigations.some((c) => c.id === id) ? id : "",
          );
        }
      } catch (e) {
        if (!abort.signal.aborted)
          setError(e instanceof Error ? e.message : "Feed unavailable");
      } finally {
        if (!abort.signal.aborted) timer = setTimeout(refresh, 500);
      }
    }
    refresh();
    const tick = setInterval(() => setNow(Date.now()), 500);
    return () => {
      abort.abort();
      clearTimeout(timer);
      clearInterval(tick);
    };
  }, [session, revision]);
  const version = state?.investigations.find((c) => c.id === selected)?.version;
  const processing = state?.investigations.find(
    (c) => c.id === selected,
  )?.processing_state;
  useEffect(() => {
    if (!selected) return;
    const abort = new AbortController();
    fetch(`/api/investigations/${encodeURIComponent(selected)}`, {
      signal: abort.signal,
    })
      .then(read)
      .then((data) => {
        if (!abort.signal.aborted) setDetail(data);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setActionError(e.message);
      });
    return () => abort.abort();
  }, [selected, version, processing, revision]);
  const live = state?.live;
  const age = live
    ? Math.max(0, (now - Date.parse(live.received_at)) / 1000)
    : 0;
  const stale = !!error || (!!live && live.status !== "FINISHED" && age > 3);
  const drivers = [...(live?.all_drivers ?? [])].sort(
    (a, b) =>
      (a.position_rank ?? 99) - (b.position_rank ?? 99) ||
      a.driver_code.localeCompare(b.driver_code),
  );
  const cases = state?.investigations ?? [];
  const shown = cases.filter(
    (c) =>
      (filter === "all" || c.workflow === filter) &&
      (!driver || c.driver === driver || c.rival === driver),
  );
  const current = selected === detail?.id ? detail : null;
  async function replay() {
    setBusy(true);
    setActionError("");
    try {
      const result = await fetch("/api/replays/field", { method: "POST" }).then(
        read,
      );
      setSession(result.session_id);
      setSelected("");
      setDriver("");
      setRevision((n) => n + 1);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Unable to start replay");
    } finally {
      setBusy(false);
    }
  }
  async function workflow() {
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
      ).then(read);
      setDetail(updated);
      setRevision((n) => n + 1);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Case update failed");
      setRevision((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="race-app">
      <a className="skip-link" href="#field">
        Skip to driver field
      </a>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">S</span>
          <div>
            <h1>STEWARD</h1>
            <p>Race control / telemetry</p>
          </div>
        </div>
        <label className="session-picker">
          <span className="sr-only">Session</span>
          <select
            aria-label="Session"
            value={session}
            onChange={(e) => {
              setSession(e.target.value);
              setSelected("");
              setDriver("");
            }}
          >
            <option value="">Latest connected session</option>
            {state?.sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <button className="button" disabled={busy} onClick={replay}>
          Replay full field
        </button>
      </header>
      <div className="race-strip">
        <div>
          <span className={`feed-state ${stale ? "warning" : ""}`}>
            {stale
              ? "FEED STALE"
              : live?.status === "LIVE"
                ? "LIVE"
                : live?.status === "REPLAY"
                  ? "REPLAY"
                  : live?.status === "FINISHED"
                    ? "REPLAY FINISHED"
                    : "AWAITING FEED"}
          </span>
          <strong>
            {live?.session_name ??
              "Connect the race feed or start a full-field replay"}
          </strong>
        </div>
        <div className="race-counters">
          <span>
            {drivers.length} <small>DRIVERS</small>
          </span>
          <span>
            {clock(live?.session_time_s ?? 0)} <small>SESSION</small>
          </span>
          <span data-testid="sample-count">
            {(live?.native_samples_processed ?? 0).toLocaleString()}{" "}
            <small>SAMPLES</small>
          </span>
          <span>
            {live?.track_status ?? "—"} <small>TRACK</small>
          </span>
        </div>
      </div>
      {error && (
        <div className="connection-notice" role="status">
          {error} Last received values may be stale.
        </div>
      )}
      {actionError && (
        <div className="connection-notice" role="alert">
          {actionError}
        </div>
      )}
      <nav className="mobile-tabs" aria-label="Workspace view">
        <button
          aria-pressed={mobileTab === "field"}
          onClick={() => setMobileTab("field")}
        >
          All drivers
        </button>
        <button
          aria-pressed={mobileTab === "reports"}
          onClick={() => setMobileTab("reports")}
        >
          Reports ({cases.filter((c) => c.workflow === "open").length})
        </button>
      </nav>
      <main className="race-workspace">
        <section
          id="field"
          className={`field-panel ${mobileTab === "field" ? "mobile-active" : ""}`}
          aria-label="All driver telemetry"
        >
          <div className="field-heading">
            <h2>
              Driver field <span>{drivers.length}</span>
            </h2>
            <p>
              {stale
                ? `Last packet ${Math.floor(age)}s ago`
                : live
                  ? `${live.source} · packet ${live.sequence}`
                  : "Every car. Every update."}
            </p>
          </div>
          {drivers.length ? (
            <div
              className="driver-grid"
              style={
                {
                  "--rows-five": Math.ceil(drivers.length / 5),
                  "--rows-four": Math.ceil(drivers.length / 4),
                } as CSSProperties
              }
            >
              {drivers.map((d) => (
                <DriverCard
                  key={d.driver_code}
                  driver={d}
                  stale={stale}
                  selected={driver === d.driver_code}
                  reports={
                    cases.filter(
                      (c) =>
                        c.workflow === "open" &&
                        (c.driver === d.driver_code ||
                          c.rival === d.driver_code),
                    ).length
                  }
                  onSelect={() => {
                    setDriver(driver === d.driver_code ? "" : d.driver_code);
                    setSelected("");
                    setRailTab("reports");
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="field-empty">
              <h2>Waiting for the starting grid</h2>
              <p>
                Connect a live recorder to monitor the entire field. Driver
                cards appear from the session roster and stay visible if a car’s
                feed drops.
              </p>
              <button className="button" onClick={replay} disabled={busy}>
                Try the 20-driver replay
              </button>
              <p className="muted">
                Recorded data · a full-field excerpt, not a live race.
              </p>
            </div>
          )}
          <div className="field-footer">
            <span>
              Telemetry runs continuously. Case review does not pause the field.
            </span>
            <span>
              — means unavailable · replay positions use completed-lap timing
            </span>
          </div>
        </section>
        <aside
          className={`report-panel ${mobileTab === "reports" ? "mobile-active" : ""}`}
          aria-label="Reporting and issues"
        >
          <div className="rail-tabs">
            <button
              aria-pressed={railTab === "reports"}
              onClick={() => setRailTab("reports")}
            >
              Reports{" "}
              <span>{cases.filter((c) => c.workflow === "open").length}</span>
            </button>
            <button
              aria-pressed={railTab === "messages"}
              onClick={() => setRailTab("messages")}
            >
              Race messages <span>{live?.race_control?.length ?? 0}</span>
            </button>
          </div>
          {railTab === "reports" ? (
            <>
              <div className="report-toolbar">
                {selected ? (
                  <button
                    className="text-button"
                    onClick={() => setSelected("")}
                  >
                    ← All reports
                  </button>
                ) : (
                  <label>
                    <span className="sr-only">Case filter</span>
                    <select
                      id="case-filter"
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                    >
                      <option value="open">Open issues</option>
                      <option value="closed">Closed</option>
                      <option value="all">All history</option>
                    </select>
                  </label>
                )}
                {driver && (
                  <button
                    className="driver-filter"
                    onClick={() => setDriver("")}
                  >
                    {driver} ×
                  </button>
                )}
                <span>
                  {
                    cases.filter(
                      (c) =>
                        c.processing_state === "queued" ||
                        c.processing_state === "processing",
                    ).length
                  }{" "}
                  queued
                </span>
              </div>
              <div className="rail-scroll" data-testid="report-scroll">
                {selected ? (
                  current ? (
                    <CaseReview
                      item={current}
                      busy={busy}
                      onWorkflow={workflow}
                    />
                  ) : (
                    <p className="empty">Loading evidence…</p>
                  )
                ) : (
                  <div data-testid="case-list">
                    {shown.length ? (
                      shown.map((c) => (
                        <button
                          className="case-item"
                          key={c.id}
                          onClick={() => {
                            setSelected(c.id);
                            setActionError("");
                          }}
                        >
                          <span className="case-meta">
                            LAP {c.lap || "—"} · {c.driver}
                            {c.rival ? ` / ${c.rival}` : ""}
                          </span>
                          <strong>{c.title}</strong>
                          <span className={`badge ${c.ruling ?? ""}`}>
                            {c.processing_state === "failed"
                              ? "Assessment failed — review needed"
                              : c.ruling
                                ? rulingLabels[c.ruling]
                                : c.processing_state}
                          </span>
                          <small>
                            {c.evidence_mode.replaceAll("_", " ")} ·{" "}
                            {c.workflow}
                          </small>
                        </button>
                      ))
                    ) : (
                      <div className="reports-empty">
                        <span className="empty-mark">✓</span>
                        <h3>
                          No{" "}
                          {filter === "closed"
                            ? "closed reports"
                            : "flagged issues"}
                          {driver ? ` for ${driver}` : ""}
                        </h3>
                        <p>
                          The field keeps streaming. New incident candidates
                          appear here when detected or submitted.
                        </p>
                        <p className="muted">
                          No flag does not prove no incident occurred.
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="rail-scroll">
              {live?.race_control?.length ? (
                [...live.race_control].reverse().map((m) => (
                  <article className="race-message" key={m.id}>
                    <small>
                      {m.category ?? "RACE CONTROL"} ·{" "}
                      {m.time ? new Date(m.time).toLocaleTimeString() : "—"}
                    </small>
                    <p>{m.message}</p>
                  </article>
                ))
              ) : (
                <p className="empty">
                  Race-control messages appear here when supplied by the live
                  feed.
                </p>
              )}
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
