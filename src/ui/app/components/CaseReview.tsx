import type { Case } from "../types/incident";
import EvidenceTimeline from "./EvidenceTimeline";
export const rulingLabels: Record<string, string> = {
  PENALTY_RECOMMENDED: "Penalty recommended",
  NO_FURTHER_ACTION: "No further action",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
  REVIEW_REQUIRED: "Review required",
};
const words = (s: string) => s.replaceAll("_", " ");

export default function CaseReview({
  item,
  busy,
  onWorkflow,
}: {
  item: Case;
  busy: boolean;
  onWorkflow: () => void;
}) {
  return (
    <div className="case-review">
      <div className="case-intro">
        <p className="eyebrow">
          Lap {item.lap || "—"} · {item.corner}
        </p>
        <h3>{item.title}</h3>
        <p className={`badge ${item.ruling ?? ""}`}>
          {item.ruling
            ? rulingLabels[item.ruling]
            : words(item.processing_state)}
          {item.penalty_seconds != null
            ? ` · ${item.penalty_seconds} seconds`
            : ""}
        </p>
        <p>
          {item.summary ??
            "Assessment queued. Telemetry continues while this case is processed."}
        </p>
        <button className="button" disabled={busy} onClick={onWorkflow}>
          {item.workflow === "open" ? "Close case" : "Reopen case"}
        </button>
      </div>
      {item.evidence_mode === "document_reconstruction" && (
        <p className="notice">
          Document reconstruction: observations come from the FIA account. This
          is a judging test, not independent detection.
        </p>
      )}
      {item.evidence_mode === "telemetry_only" && (
        <p className="notice">
          Telemetry only: overlap, contact and responsibility require additional
          evidence.
        </p>
      )}
      <EvidenceTimeline samples={item.samples ?? []} />
      <details className="detail-section" open>
        <summary>Rule conditions</summary>
        <ul className="conditions">
          {item.conditions?.map((c) => (
            <li key={c.predicate}>
              <span>{words(c.predicate)}</span>
              <strong>{c.status}</strong>
              <small>
                {c.evidence_ids.join(", ") || "No qualifying evidence"}
              </small>
            </li>
          ))}
        </ul>
        {!item.conditions?.length && <p>No supported rule pattern yet.</p>}
      </details>
      <details className="detail-section">
        <summary>Alternative explanation & missing facts</summary>
        <p>{item.alternative_explanation}</p>
        <p className="muted">{item.missing_facts?.map(words).join("; ")}</p>
      </details>
      <details className="detail-section">
        <summary>Observations & provenance</summary>
        {item.observations?.map((e) => (
          <div className="observation" key={e.id}>
            <strong>
              {e.id} · {words(e.predicate)}: {e.value ? "yes" : "no"}
            </strong>
            <p>{e.detail}</p>
            <small>
              {e.verified ? "Reviewed" : "Unverified"} · {words(e.source)}
            </small>
            {e.source_ref.startsWith("https://") ? (
              <a href={e.source_ref} target="_blank" rel="noreferrer">
                Open evidence source ↗
              </a>
            ) : (
              <small>{e.source_ref}</small>
            )}
          </div>
        ))}
      </details>
      <details className="detail-section">
        <summary>Applicable rules</summary>
        {item.rules?.map((r) => (
          <div className="observation" key={r.id}>
            <strong>{r.title}</strong>
            <p>{r.text}</p>
            <a
              href={`${r.url}#page=${r.page}`}
              target="_blank"
              rel="noreferrer"
            >
              Source document · page {r.page} ↗
            </a>
          </div>
        ))}
      </details>
      <details className="detail-section">
        <summary>Model review & limitations</summary>
        <p>Model: {item.model_review?.status ?? "pending"}</p>
        <p>{item.model_review?.summary}</p>
        <ul>
          {item.limitations?.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        <p className="muted">
          No calibrated probability; penalty points require separate review.
        </p>
      </details>
      <details className="detail-section">
        <summary>Case history</summary>
        <ul>
          {item.audit?.map((a, i) => (
            <li key={i}>
              {words(a.action)} · {new Date(a.timestamp).toLocaleTimeString()}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
