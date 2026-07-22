"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  ChatMessage,
  ChatRequest,
  MapData,
  CyclePoint,
  WorkspaceContext,
  PlotItem,
  FilterState,
  WorkspaceMode,
  PlotlyFigure,
  EMPTY_FILTERS,
} from "@/types";
import { sendChatMessage, getErrorMessage, getInitialRegistry } from "@/services/api";
import { generateId, applyFilters } from "@/lib/utils";

interface UseChatReturn {
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  sendMessage: (customText?: string) => Promise<void>;
  handleKeyDown: (e: React.KeyboardEvent) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  onSelectSuggestion: (query: string) => void;
  selectedFloat: string | null;
  setSelectedFloat: (floatId: string | null) => void;

  // Redesign: workspace state machine + panels
  currentMapData: MapData[];
  mode: WorkspaceMode;
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
  context: WorkspaceContext;

  cycleData: CyclePoint[] | null;
  isLoadingCycles: boolean;
  highlightCycle: number | null;
  setHighlightCycle: (n: number | null) => void;

  plotItems: PlotItem[];
  plotDrawerOpen: boolean;
  setPlotDrawerOpen: (open: boolean) => void;
  togglePlotPin: (id: string) => void;

  filters: FilterState;
  setFilters: (f: FilterState) => void;
  filteredMapData: MapData[];
  availableFilterOptions: {
    networks: string[];
    dacs: string[];
    variables: string[];
    statuses: string[];
  };
  // Reliable count for sidebar "Active Floats" even on initial load
  floatCount: number;

  floatSearch: string;
  setFloatSearch: (s: string) => void;
  submitFloatSearch: () => void;
  loadCycleHistory: (floatId: string) => Promise<void>;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [selectedFloat, setSelectedFloat] = useState<string | null>(null);
  const sessionIdRef = useRef<string>(generateId());
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const isNearBottomRef = useRef(true);
  const prevMessageCountRef = useRef(messages.length);

  // Redesign state
  const [mode, setMode] = useState<WorkspaceMode>("chat");
  const [chatOpen, setChatOpenState] = useState(false);
  const [cycleData, setCycleData] = useState<CyclePoint[] | null>(null);
  const [isLoadingCycles, setIsLoadingCycles] = useState(false);
  const [highlightCycle, setHighlightCycle] = useState<number | null>(null);
  const [plotItems, setPlotItems] = useState<PlotItem[]>([]);
  const [plotDrawerOpen, setPlotDrawerOpen] = useState(false);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [floatSearch, setFloatSearch] = useState("");

  // NEW: initial live registry for dashboard (populated on app start)
  const [initialMapData, setInitialMapData] = useState<MapData[]>([]);
  const [isBootstrapLoading, setIsBootstrapLoading] = useState(true);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || !messagesEndRef.current) return;

    const newCount = messages.length;
    const prevCount = prevMessageCountRef.current;
    prevMessageCountRef.current = newCount;

    if (newCount > prevCount && isNearBottomRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const onScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const { scrollTop, scrollHeight, clientHeight } = container;
    isNearBottomRef.current = scrollTop + clientHeight >= scrollHeight - 100;
  }, []);

  const chatMapData = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((m) => m.role === "assistant" && !m.isLoading && m.mapData)?.mapData ?? [],
    [messages]
  );

  // Prefer bootstrap live registry for initial dashboard (filters + map) until chat produces data.
  // This ensures sidebar and map are populated immediately on startup.
  const currentMapData = useMemo(
    () => (initialMapData.length > 0 ? initialMapData : chatMapData),
    [initialMapData, chatMapData]
  );

  // ── Load cycle history / trajectory on explicit action (defined early for closure) ───────────────────
  const loadCycleHistory = useCallback(
    async (floatId: string) => {
      if (isLoadingCycles) return;
      setIsLoadingCycles(true);
      try {
        const response = await sendChatMessage(
          { message: `Show trajectory of float ${floatId}` },
          sessionIdRef.current
        );
        const mapData = response.map_data ?? [];
        const ordered = (mapData || [])
          .filter((m: any) => m.float_id === floatId)
          .sort((a: any, b: any) => (a.profile_number ?? 0) - (b.profile_number ?? 0));
        const cycles: CyclePoint[] = ordered.map((m: any, idx: number) => ({
          cycleNumber: m.profile_number ?? idx + 1,
          date: m.profile_date,
          latitude: m.latitude,
          longitude: m.longitude,
          variables: m.variables ?? [],
          index: idx,
          isDeployment: idx === 0,
          isCurrent: idx === ordered.length - 1,
        }));
        setCycleData(cycles.length > 0 ? cycles : null);
        setHighlightCycle(null);
      } catch {
        setCycleData(null);
      } finally {
        setIsLoadingCycles(false);
      }
    },
    [isLoadingCycles]
  );

  // ── Workflow: selecting a float swaps the right column to metadata ───────
  // Single click: immediately select + show metadata + cycle history (no auto chat)
  const handleSelectFloat = useCallback(async (floatId: string | null) => {
    setSelectedFloat(floatId);
    if (floatId) {
      setMode("metadata");
      setChatOpenState(false);
      setHighlightCycle(null);
      try {
        await loadCycleHistory(floatId);
      } catch {
        // ignore, CycleHistory will show empty state
      }
    } else {
      setMode("chat");
      setChatOpenState(false);
      setCycleData(null);
    }
  }, [loadCycleHistory]);

  // Toggling the chat overlay must NOT clear conversation or selection.
  const setChatOpen = useCallback((open: boolean) => {
    setChatOpenState(open);
  }, []);

  // ── Derive the Current Context for the AI copilot ───────────────────────
  const context: WorkspaceContext = useMemo(() => {
    const sel = selectedFloat
      ? currentMapData.find((m) => m.float_id === selectedFloat)
      : undefined;
    const lastTrajectory =
      [...messages]
        .reverse()
        .find((m) => m.role === "assistant" && m.intent === "trajectory" && m.mapData)?.mapData ?? [];
    const cyclePoint = highlightCycle != null
      ? lastTrajectory.find((m) => m.profile_number === highlightCycle)
      : undefined;
    return {
      floatId: selectedFloat,
      cycle: highlightCycle,
      region: sel?.status ? null : null,
      variables: cyclePoint?.variables ?? sel?.variables ?? [],
    };
  }, [selectedFloat, currentMapData, messages, highlightCycle]);

  // ── Filters: derive options from current markers OR initial bootstrap data ─
  const sourceDataForFilters = useMemo(
    () => (initialMapData.length > 0 ? initialMapData : currentMapData),
    [initialMapData, currentMapData]
  );

  const availableFilterOptions = useMemo(() => {
    const nets = new Set<string>();
    const dacs = new Set<string>();
    const vars = new Set<string>();
    const statuses = new Set<string>();
    for (const m of sourceDataForFilters) {
      nets.add(m.network || "Core Argo");
      if (m.dac) dacs.add(m.dac);
      for (const v of m.variables || []) vars.add(v.toUpperCase());
      if (m.status) statuses.add(m.status);
    }
    // Robust fallbacks so UI is never empty on first load
    const result = {
      networks: Array.from(nets).sort(),
      dacs: Array.from(dacs).sort(),
      variables: Array.from(vars).sort(),
      statuses: Array.from(statuses).sort(),
    };
    if (result.networks.length === 0) result.networks = ["Core Argo", "BGC Argo"];
    if (result.dacs.length === 0) result.dacs = ["INCOIS", "Coriolis", "AOML"];
    if (result.variables.length === 0) result.variables = ["TEMP", "PSAL", "DOXY", "CHLA"];
    if (result.statuses.length === 0) result.statuses = ["active", "inactive"];
    return result;
  }, [sourceDataForFilters]);

  const filteredMapData = useMemo(() => {
    const { applyFilters } = require("@/lib/utils") as typeof import("@/lib/utils");
    return applyFilters(currentMapData, filters);
  }, [currentMapData, filters]);

  // Reliable count for "Active Floats" — now reflects filters
  const totalFloatCount = filteredMapData.length;

  // Bootstrap using the new dedicated registry endpoint (no LLM, no chat).
  const bootstrapInitialRegistry = useCallback(async () => {
    setIsBootstrapLoading(true);
    try {
      const resp: any = await getInitialRegistry();  // now calls /api/v1/floats/registry
      const data = resp.map_data || resp.data || resp || [];
      if (Array.isArray(data) && data.length > 0) {
        setInitialMapData(data);
      } else if (resp && Array.isArray(resp)) {
        setInitialMapData(resp);
      }

      // If the endpoint also returned pre-computed filter options, we can use them
      // (the current availableFilterOptions memo will also derive from map_data)
    } catch (e) {
      console.warn("Initial registry bootstrap failed", e);
    } finally {
      setIsBootstrapLoading(false);
    }
  }, []);

  useEffect(() => {
    bootstrapInitialRegistry();
  }, [bootstrapInitialRegistry]);

  // ── Send a chat message ──────────────────────────────────────────────────
  const sendMessage = useCallback(
    async (customText?: string) => {
      const queryText = (customText ?? input).trim();
      if (!queryText || isLoading) return;

      // Sending a free-text query returns focus to the chat experience.
      setSelectedFloat(null);
      setMode("chat");

      const userMessage: ChatMessage = {
        id: generateId(),
        role: "user",
        content: queryText,
        timestamp: new Date(),
      };

      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: "assistant",
        content: "",
        timestamp: new Date(),
        isLoading: true,
      };

      isNearBottomRef.current = true;

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      if (!customText) setInput("");
      setIsLoading(true);

      try {
        const request: ChatRequest = { message: queryText };
        const response = await sendChatMessage(request, sessionIdRef.current);

        const figures: PlotlyFigure[] | null = response.figures ?? null;

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessage.id
              ? {
                  ...msg,
                  content: response.message,
                  figure: response.figure,
                  figures,
                  summary: response.data_summary,
                  intent: response.intent,
                  mapData: response.map_data,
                  isLoading: false,
                }
              : msg
          )
        );

        // Populate the plot drawer from per-variable figures when present.
        if (figures && figures.length > 0) {
          setPlotItems(
            figures.map((f, i) => ({
              id: `${response.intent}-${i}-${f.variable ?? "var"}`,
              variable: f.variable ?? "var",
              title: f.variable ?? `Plot ${i + 1}`,
              figure: f,
              pinned: false,
            }))
          );
          setPlotDrawerOpen(true);
        }
      } catch (error) {
        const errorMessage = getErrorMessage(error);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessage.id
              ? {
                  ...msg,
                  content: `Sorry, I encountered an error: ${errorMessage}`,
                  isLoading: false,
                  error: errorMessage,
                }
              : msg
          )
        );
      } finally {
        setIsLoading(false);
      }
    },
    [input, isLoading]
  );

  // Auto-load cycles (kept for legacy trajectory responses)
  useEffect(() => {
    if (!selectedFloat) {
      setCycleData(null);
      return;
    }
    const trajForFloat = [...messages]
      .reverse()
      .find(
        (m) =>
          m.role === "assistant" &&
          m.intent === "trajectory" &&
          m.mapData?.some((mm) => mm.float_id === selectedFloat)
      );
    if (trajForFloat?.mapData) {
      const ordered = trajForFloat.mapData
        .filter((m) => m.float_id === selectedFloat)
        .sort((a, b) => (a.profile_number ?? 0) - (b.profile_number ?? 0));
      setCycleData(
        ordered.map((m, idx) => ({
          cycleNumber: m.profile_number ?? idx + 1,
          date: m.profile_date,
          latitude: m.latitude,
          longitude: m.longitude,
          variables: m.variables ?? [],
          index: idx,
          isDeployment: idx === 0,
          isCurrent: idx === ordered.length - 1,
        })) ?? null
      );
    }
  }, [selectedFloat, messages]);

  // ── Plot drawer pin toggle ───────────────────────────────────────────────
  const togglePlotPin = useCallback((id: string) => {
    setPlotItems((prev) =>
      prev.map((p) => (p.id === id ? { ...p, pinned: !p.pinned } : p))
    );
  }, []);

  // ── Header float-ID search ───────────────────────────────────────────────
  const submitFloatSearch = useCallback(() => {
    const fid = floatSearch.trim();
    if (!fid) return;
    sendMessage(`Sensors on float ${fid.replace(/\D/g, "")}`);
  }, [floatSearch, sendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    },
    [sendMessage]
  );

  // ── Suggestion chip handler ──────────────────────────────────────────────
  const onSelectSuggestion = useCallback(
    (query: string) => {
      sendMessage(query);
    },
    [sendMessage]
  );

  return {
    messages,
    input,
    setInput,
    isLoading,
    sendMessage,
    handleKeyDown,
    messagesEndRef,
    scrollContainerRef,
    onScroll,
    onSelectSuggestion,
    selectedFloat,
    setSelectedFloat: handleSelectFloat,
    currentMapData,
    mode,
    chatOpen,
    setChatOpen,
    context,
    cycleData,
    isLoadingCycles,
    highlightCycle,
    setHighlightCycle,
    plotItems,
    plotDrawerOpen,
    setPlotDrawerOpen,
    togglePlotPin,
    filters,
    setFilters,
    filteredMapData,
    availableFilterOptions,
    floatCount: totalFloatCount,
    floatSearch,
    setFloatSearch,
    submitFloatSearch,
    loadCycleHistory,
  } as UseChatReturn;
}
