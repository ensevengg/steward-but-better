export type Ruling =
  | "PENALTY_RECOMMENDED"
  | "NO_FURTHER_ACTION"
  | "INSUFFICIENT_EVIDENCE"
  | "REVIEW_REQUIRED";
export type Driver = {
  driver_code: string;
  position_rank: number | null;
  current_speed: number | null;
  lap_number: number | null;
  delta_to_leader: number | null;
  status: string;
  driver_number?: string | null;
  team?: string | null;
  team_color?: string | null;
  throttle?: number | null;
  brake_applied?: boolean | null;
  gear?: number | null;
  rpm?: number | null;
  drs?: number | null;
  lateral_g?: number | null;
  longitudinal_g?: number | null;
  sample_time_s?: number | null;
  gap_text?: string | null;
  timing_source?: string | null;
};
export type Observation = {
  id: string;
  predicate: string;
  value: boolean;
  verified: boolean;
  source: string;
  source_ref: string;
  detail: string;
  time_s: number | null;
};
export type Sample = {
  driver: string;
  session_time_s: number;
  speed_kph: number | null;
  lateral_g: number | null;
  longitudinal_g: number | null;
};
export type Case = {
  id: string;
  title: string;
  session_id: string;
  event_date: string;
  driver: string;
  rival: string | null;
  lap: number;
  corner: string;
  incident_type: string;
  evidence_mode: string;
  ruling?: Ruling;
  penalty_seconds?: number | null;
  penalty_points?: number | null;
  summary?: string;
  alternative_explanation?: string;
  workflow: "open" | "closed";
  version: number;
  processing_state: string;
  updated_at: string;
  missing_facts?: string[];
  limitations?: string[];
  observations?: Observation[];
  samples?: Sample[];
  conditions?: { predicate: string; status: string; evidence_ids: string[] }[];
  rules?: {
    id: string;
    title: string;
    url: string;
    page: number;
    text: string;
    authority: string;
  }[];
  model_review?: {
    status: string;
    model?: string;
    summary?: string;
    alternative_explanation?: string;
  };
  audit?: { action: string; timestamp: string }[];
};
export type Dashboard = {
  sessions: { id: string; name: string }[];
  live: {
    session_id: string;
    session_name: string;
    event_date: string;
    status: string;
    sequence: number;
    session_time_s: number;
    received_at: string;
    all_drivers: Driver[];
    native_samples_processed: number;
    source: string;
    track_status?: string | null;
    race_control: {
      id: string;
      message: string;
      time?: string;
      category?: string;
    }[];
  } | null;
  investigations: Case[];
  server_time: string;
};
