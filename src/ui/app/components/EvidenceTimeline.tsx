import { useMemo } from "react";
import type { Sample } from "../types/incident";

export default function EvidenceTimeline({ samples }: { samples: Sample[] }) {
  const series = useMemo(() => {
    const groups = new Map<string, Sample[]>();
    for (const s of samples) {
      const rows = groups.get(s.driver) ?? [];
      rows.push(s);
      groups.set(s.driver, rows);
    }
    return [...groups].map(([driver, rows]) => ({
      driver,
      rows: rows.sort((a, b) => a.session_time_s - b.session_time_s),
    }));
  }, [samples]);
  if (!samples.length)
    return <p className="footnote">No sample timeline supplied.</p>;
  const start = Math.min(...samples.map((s) => s.session_time_s));
  const end = Math.max(...samples.map((s) => s.session_time_s));
  const colors = ["#8eb5cc", "#c9b685", "#a6b99b", "#c3a7c5"];
  return (
    <section className="detail-section">
      <h4>Synchronized speed timeline</h4>
      <p className="muted">
        Recorded samples · {start.toFixed(1)}–{end.toFixed(1)}s session time
      </p>
      <svg
        viewBox="0 0 600 180"
        role="img"
        aria-label="Speed traces aligned on session time, from zero to 400 kilometres per hour"
      >
        {[0, 100, 200, 300, 400].map((v) => (
          <g key={v}>
            <line
              x1="35"
              x2="590"
              y1={155 - (v / 400) * 140}
              y2={155 - (v / 400) * 140}
              stroke="var(--line)"
            />
            <text
              x="1"
              y={159 - (v / 400) * 140}
              fill="var(--muted)"
              fontSize="11"
            >
              {v}
            </text>
          </g>
        ))}
        {series.map(({ driver, rows }, index) => {
          let previous: number | null = null;
          const path = rows
            .map((s) => {
              if (s.speed_kph === null) {
                previous = null;
                return "";
              }
              const command =
                previous === null || s.session_time_s - previous > 1
                  ? "M"
                  : "L";
              previous = s.session_time_s;
              return `${command}${35 + ((s.session_time_s - start) / Math.max(1, end - start)) * 555},${155 - (s.speed_kph / 400) * 140}`;
            })
            .join(" ");
          return (
            <path
              key={driver}
              d={path}
              fill="none"
              stroke={colors[index % colors.length]}
              strokeWidth="2"
            />
          );
        })}
        <text x="35" y="175" fill="var(--muted)" fontSize="11">
          {start.toFixed(1)}s
        </text>
        <text x="550" y="175" fill="var(--muted)" fontSize="11">
          {end.toFixed(1)}s
        </text>
      </svg>
      <div className="legend">
        {series.map(({ driver }, i) => (
          <span key={driver}>
            <i style={{ background: colors[i % colors.length] }} />
            {driver}
          </span>
        ))}
      </div>
      <details>
        <summary>Sample values ({samples.length})</summary>
        <div className="sample-table">
          <table>
            <thead>
              <tr>
                <th>Driver</th>
                <th>Time (s)</th>
                <th>km/h</th>
                <th>Lateral G</th>
              </tr>
            </thead>
            <tbody>
              {samples.map((s, i) => (
                <tr key={i}>
                  <td>{s.driver}</td>
                  <td>{s.session_time_s.toFixed(2)}</td>
                  <td>{s.speed_kph?.toFixed(1) ?? "—"}</td>
                  <td>{s.lateral_g?.toFixed(2) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
