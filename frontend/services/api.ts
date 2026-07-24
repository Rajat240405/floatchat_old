import axios, { AxiosError } from "axios";
import {
  ChatRequest,
  ChatResponse,
  HealthResponse,
  MapData,
  FloatRegistryInfo,
  PlotlyFigure,
  DataSummary,
} from "@/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const api = axios.create({
  baseURL: BACKEND_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 180000,
});

type JsonRequestTelemetry = {
  requestStartMs: number;
  apiResponseTimeMs: number;
  jsonParseTimeMs: number;
};

async function fetchJsonWithTelemetry<T>(
  url: string,
  init?: RequestInit
): Promise<{ data: T; telemetry: JsonRequestTelemetry }> {
  const requestStartMs = performance.now();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 180000);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const responseText = await response.text();
    const apiResponseTimeMs = performance.now() - requestStartMs;
    if (!response.ok) {
      throw new Error(`Request failed (${response.status}): ${responseText.slice(0, 240)}`);
    }
    const parseStartMs = performance.now();
    const data = JSON.parse(responseText) as T;
    const jsonParseTimeMs = performance.now() - parseStartMs;
    return {
      data,
      telemetry: { requestStartMs, apiResponseTimeMs, jsonParseTimeMs },
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

// ── Chat (LLM path — natural language ONLY) ───────────────────────────────

export async function sendChatMessage(
  request: ChatRequest,
  sessionId?: string
): Promise<ChatResponse> {
  const payload: ChatRequest = { ...request };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  const result = await fetchJsonWithTelemetry<ChatResponse>(
    `${BACKEND_URL}/api/v1/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return { ...result.data, telemetry: result.telemetry };

}

export async function checkHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>("/health");
  return data;
}

// ── Deterministic float resources (NO LLM) ────────────────────────────────

export async function getFloatRegistry(): Promise<{
  float_count: number;
  map_data: MapData[];
  networks: string[];
  dacs: string[];
  variables: string[];
  statuses: string[];
}> {
  const { data } = await api.get("/api/v1/floats/registry");
  return data;
}

export async function getInitialRegistry(): Promise<{
  float_count: number;
  map_data: MapData[];
  networks: string[];
  dacs: string[];
  variables: string[];
  statuses: string[];
}> {
  try {
    return await getFloatRegistry();
  } catch {
    return {
      float_count: 0,
      map_data: [],
      networks: [],
      dacs: [],
      variables: [],
      statuses: [],
    };
  }
}

/** GET /api/v1/floats/{id}/metadata — no LLM */
export async function getFloatMetadata(floatId: string): Promise<{
  float_info: FloatRegistryInfo;
  map_data: MapData[];
}> {
  const { data } = await api.get(`/api/v1/floats/${encodeURIComponent(floatId)}/metadata`);
  return data;
}

/** GET /api/v1/floats/{id}/trajectory — full cycle history, no LLM */
export async function getFloatTrajectory(floatId: string): Promise<{
  float_id: string;
  cycle_count: number;
  map_data: MapData[];
  distance_km: number | null;
  date_range: { min?: string | null; max?: string | null };
}> {
  const { data } = await api.get(
    `/api/v1/floats/${encodeURIComponent(floatId)}/trajectory`
  );
  return data;
}

/** GET /api/v1/floats/{id}/latest-profile — plot only, no LLM */
export async function getFloatLatestProfile(floatId: string): Promise<{
  float_id: string;
  intent: string;
  message: string;
  figure: PlotlyFigure | null;
  figures: PlotlyFigure[] | null;
  data_summary: DataSummary;
  map_data: MapData[];
}> {
  const { data } = await api.get(
    `/api/v1/floats/${encodeURIComponent(floatId)}/latest-profile`
  );
  return data;
}

export interface AvailablePlotItem {
  variable: string;
  title: string;
  profiles: number;
}

/** GET /api/v1/floats/{id}/available-plots — catalogue only, no LLM */
export async function getFloatAvailablePlots(floatId: string): Promise<{
  float_id: string;
  plots: AvailablePlotItem[];
}> {
  const { data } = await api.get(
    `/api/v1/floats/${encodeURIComponent(floatId)}/available-plots`
  );
  return data;
}

/** GET /api/v1/floats/{id}/plot?variable=TEMP — deterministic plot, no LLM */
export async function getFloatVariablePlot(
  floatId: string,
  variable: string,
  profileNumber?: number | null
): Promise<{
  float_id: string;
  intent: string;
  message: string;
  figure: PlotlyFigure | null;
  figures: PlotlyFigure[] | null;
  data_summary: DataSummary;
  map_data: MapData[];
  telemetry: {
    requestStartMs: number;
    apiResponseTimeMs: number;
    jsonParseTimeMs: number;
  };
}> {
  // Use fetch for this diagnostic endpoint so network transfer and JSON.parse
  // can be measured separately. Other API calls retain the existing Axios path.
  const requestStartMs = performance.now();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 180000);
  try {
    const response = await fetch(
      `${BACKEND_URL}/api/v1/floats/${encodeURIComponent(floatId)}/plot?variable=${encodeURIComponent(variable)}${profileNumber != null ? `&profile_number=${encodeURIComponent(profileNumber)}` : ""}`, 
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
      }
    );
    const responseText = await response.text();
    const apiResponseTimeMs = performance.now() - requestStartMs;
    if (!response.ok) {
      throw new Error(`Plot request failed (${response.status}): ${responseText.slice(0, 240)}`);
    }
    const parseStartMs = performance.now();
    const data = JSON.parse(responseText);
    const jsonParseTimeMs = performance.now() - parseStartMs;
    return {
      ...data,
      telemetry: { requestStartMs, apiResponseTimeMs, jsonParseTimeMs },
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    if (error.response?.data?.message) {
      return error.response.data.message;
    }
    if (error.code === "ECONNABORTED") {
      return "Request timed out. The backend may be busy processing data.";
    }
    if (error.code === "ERR_NETWORK") {
      return "Cannot connect to backend. Please ensure the FloatChat server is running on port 8000.";
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred.";
}
