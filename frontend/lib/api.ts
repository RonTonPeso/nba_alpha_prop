const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

export type ComparisonRow = {
  player_id: number;
  player_name: string;
  game_id: string;
  game_date: string;
  prop_type: string;
  line: number;
  model_version: string;
  model_p: number;
  market_mid: number | null;
  gap: number | null;
  low_confidence: boolean;
  mean: number;
  std: number;
};

export type ComparisonsToday = {
  date: string;
  as_of: string;
  count: number;
  rows: ComparisonRow[];
};

export type PlayerDetail = {
  player_id: number;
  player_name: string;
  game_id: string | null;
  game_date: string | null;
  prop_type: string;
  model_version: string | null;
  mean: number | null;
  std: number | null;
  quantile_10: number | null;
  quantile_50: number | null;
  quantile_90: number | null;
  low_confidence: boolean | null;
  distribution: string | null;
  density: { x: number; density: number }[];
  market_line: number | null;
  market_mid: number | null;
  model_p: number | null;
  gap: number | null;
  shap_top5: { feature: string; shap: number }[];
  injuries: {
    injury_signal_id: number;
    claim_type: string;
    severity: string | null;
    confidence: number;
    source: string;
    event_time: string;
    player_name_raw: string;
    raw_text: string;
  }[];
  comparisons: ComparisonRow[];
};

export type CalibrationSummary = {
  title: string;
  source_files: string[];
  bins: {
    lower: number;
    upper: number;
    count: number;
    mean_predicted: number | null;
    realized_rate: number | null;
  }[];
  calibration_error: number | null;
  brier: number | null;
  n_contracts: number | null;
  disagreement_note: string | null;
  props: {
    prop_type: string;
    model_version: string;
    brier: number | null;
    residual_brier: number | null;
    n_contracts: number | null;
    source: string;
  }[];
  raw_notes: string[];
};

export type StatusResponse = {
  scheduler_enabled: boolean;
  job_ids: string[];
  freshness: {
    table: string;
    max_available_at: string | null;
    max_ingested_at: string | null;
    row_count: number | null;
  }[];
  api_version: string;
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} for ${path}`);
  }
  return response.json() as Promise<T>;
}

export function fetchComparisonsToday(date?: string) {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return getJson<ComparisonsToday>(`/api/comparisons/today${qs}`);
}

export function fetchComparisonDates() {
  return getJson<{ dates: string[] }>("/api/comparisons/dates");
}

export function fetchPlayerDetail(
  playerId: number,
  params?: { game_id?: string; prop_type?: string },
) {
  const search = new URLSearchParams();
  if (params?.game_id) search.set("game_id", params.game_id);
  if (params?.prop_type) search.set("prop_type", params.prop_type);
  const qs = search.toString() ? `?${search}` : "";
  return getJson<PlayerDetail>(`/api/players/${playerId}/detail${qs}`);
}

export function fetchCalibration() {
  return getJson<CalibrationSummary>("/api/calibration/summary");
}

export function fetchStatus() {
  return getJson<StatusResponse>("/api/status");
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatGap(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const signed = value >= 0 ? `+${(value * 100).toFixed(1)}` : (value * 100).toFixed(1);
  return `${signed} pp`;
}
