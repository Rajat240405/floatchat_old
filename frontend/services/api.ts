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
