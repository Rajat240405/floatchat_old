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

// ── Chat (LLM path — natural language ONLY) ───────────────────────────────

export async function sendChatMessage(
  request: ChatRequest,
  sessionId?: string
): Promise<ChatResponse> {
  const payload: ChatRequest = { ...request };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  const { data } = await api.post<ChatResponse>("/api/v1/chat", payload);
  return data;
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
