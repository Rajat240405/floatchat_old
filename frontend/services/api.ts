import axios, { AxiosError } from "axios";
import { ChatRequest, ChatResponse, HealthResponse } from "@/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const api = axios.create({
  baseURL: BACKEND_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 180000,
});

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

// Bootstrap to populate live dashboard filters + map immediately on startup.
//
// IMPORTANT: WORKAROUND — uses a hardcoded natural-language query.
//
// Why this approach:
// - The UI requires immediate population of SidebarFilters (Network, DAC, Variables, Status)
//   + Active Float count + MapPanel markers on first load (no user query required).
// - The only public endpoint that returns `map_data` (list of float locations + metadata)
//   is the conversational `/chat` endpoint.
// - A previous attempt using the message "bootstrap initial float registry for dashboard filters"
//   sometimes returned empty map_data (unreliable intent classification / data lake match).
// - "floats in arabian sea" is a proven, reliable query that triggers a region_search
//   against the local data lake and reliably returns real map_data (floats in Arabian Sea).
//
// This is a TEMPORARY WORKAROUND to restore "live on startup" behavior after regressions.
//
// RECOMMENDED LONG-TERM SOLUTION:
//   Add a dedicated, lightweight backend endpoint (e.g. GET /api/v1/floats/registry
//   or GET /api/v1/bootstrap) that directly exposes float registry data from
//   float_registry.parquet (via lake.get_float_registry()) + derived filter options.
//   The frontend bootstrap should call that instead of a chat message.
//
// Do NOT change the query string here without also updating backend expectations
// and re-testing filter population on clean startup.
export async function getFloatRegistry(): Promise<any> {
  const { data } = await api.get<any>("/api/v1/floats/registry");
  return data;
}

// Alias for bootstrap (preserves prior call sites)
export async function getInitialRegistry(): Promise<any> {
  try {
    return await getFloatRegistry();
  } catch (e) {
    // graceful fallback (empty registry)
    return { float_count: 0, map_data: [], networks: [], dacs: [], variables: [], statuses: [] };
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
