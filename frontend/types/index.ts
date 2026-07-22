// ── Map & float data ──────────────────────────────────────────────────────

export interface MapData {
  float_id: string;
  latitude: number;
  longitude: number;
  profile_date: string | null;
  profile_number?: number | null;
  dac: string;
  variables: string[];
  selected: boolean;
  status?: string;
  manufacturer?: string | null;
  profiler_type?: string | null;
  /** Argo network: "Core Argo" | "BGC Argo". First-class filter attribute. */
  network?: string | null;
  /** WMO identifier (mirrors float_id when not distinct). */
  wmo_id?: string | null;
}

export interface FloatRegistryInfo {
  float_id: string;
  found: boolean;
  status: string;
  sensors: string[];
  institution: string;
  platform_type: string;
  profiler_type: string;
  first_profile_date: string | null;
  last_report_date: string | null;
  profile_count: number;
  region_tag?: string | null;
  last_lat?: number | null;
  last_lon?: number | null;
  manufacturer?: string | null;
  battery_voltage?: number | null;
  battery_percentage?: number | null;
  battery_status?: string | null;
  battery_note?: string | null;
  // Redesign: first-class scientific attributes (additive; backend-derived).
  wmo_id?: string;
  /** "Core Argo" | "BGC Argo". */
  network?: string;
  /** Resolved data-assembly-centre name (e.g. "INCOIS (India)"). */
  dac?: string;
  /** Deployment date (proxied from first_profile_date until authoritative). */
  deployment_date?: string | null;
  last_global_report_date?: string | null;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
}

export interface PlotlyFigure {
  data: PlotlyTrace[];
  layout: Record<string, unknown>;
  /** Canonical Argo variable code for per-variable drawer figures. */
  variable?: string;
}

export interface PlotlyTrace {
  x: number[];
  y: number[];
  mode: string;
  name: string;
  type?: string;
  line?: Record<string, unknown>;
  marker?: Record<string, unknown>;
  hovertext?: string[];
  hoverinfo?: string;
  showlegend?: boolean;
  xaxis?: string;
  yaxis?: string;
}

export interface DataSummary {
  matched_records?: number;
  total_measurements?: number;
  unique_profiles?: number;
  unique_floats?: number;
  date_range?: {
    min: string | null;
    max: string | null;
  };
  files?: string[];
  readable?: number;
  float_info?: FloatRegistryInfo;
  radius_km?: number;
  distance_km?: number;
  nearest_float_id?: string;
  target_coords?: { lat: number; lon: number };
  center?: { lat: number; lon: number };
  existence?: boolean;
  // Trajectory-specific (intent === "trajectory")
  float_id?: string;
  trajectory_points?: number;
  trajectory_path?: [number, number][];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  figure?: PlotlyFigure | null;
  /** Per-variable figures for the stacked plot drawer. */
  figures?: PlotlyFigure[] | null;
  summary?: DataSummary;
  intent?: string;
  mapData?: MapData[];
  isLoading?: boolean;
  error?: string;
}

export interface HealthResponse {
  status: string;
  metadata_loaded: boolean;
}

// ── Redesign: new domain types ────────────────────────────────────────────

/** A single cycle/profile row in the Float Cycle History table. */
export interface CyclePoint {
  cycleNumber: number;
  date: string | null;
  latitude: number;
  longitude: number;
  variables: string[];
  /** 0-based index within the trajectory (deployment = 0). */
  index: number;
  isDeployment: boolean;
  isCurrent: boolean;
}

/** The current scientific context surfaced in the AI copilot panel. */
export interface WorkspaceContext {
  floatId: string | null;
  cycle: number | null;
  region: string | null;
  variables: string[];
}

/** A stacked scientific plot in the slide-out analysis drawer. */
export interface PlotItem {
  id: string;
  variable: string;
  title: string;
  figure: PlotlyFigure;
  pinned: boolean;
}

/** Scientific sidebar filter state. */
export interface FilterState {
  region: string;            // "" = all
  networks: string[];        // ["Core Argo"] etc.
  dacs: string[];            // ["INCOIS (India)"] etc.
  variables: string[];       // ["DOXY"] etc.
  statuses: string[];        // ["active"] etc.
  dateFrom: string;          // ISO date or ""
  dateTo: string;            // ISO date or ""
}

export const EMPTY_FILTERS: FilterState = {
  region: "",
  networks: [],
  dacs: [],
  variables: [],
  statuses: [],
  dateFrom: "",
  dateTo: "",
};

/** Workspace display mode for the right column. */
export type WorkspaceMode = "chat" | "metadata";
