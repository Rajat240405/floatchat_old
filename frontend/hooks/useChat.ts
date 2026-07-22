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
import { sendChatMessage, getErrorMessage } from "@/services/api";
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

  floatSearch: string;
  setFloatSearch: (s: string) => void;
  submitFloatSearch: () => void;
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

  const currentMapData = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((m) => m.role === "assistant" && !m.isLoading && m.mapData)?.mapData ?? [],
    [messages]
  );

  // ── Workflow: selecting a float swaps the right column to metadata ───────
  const handleSelectFloat = useCallback((floatId: string | null) => {
    setSelectedFloat(floatId);
    if (floatId) {
      setMode("metadata");
      setChatOpenState(false);
      setCycleData(null);
      setHighlightCycle(null);
    } else {
      setMode("chat");
      setChatOpenState(false);
    }
  }, []);

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
      region: sel?.status ? null : null, // region surfaced from query context below
      variables: cyclePoint?.variables ?? sel?.variables ?? [],
    };
  }, [selectedFloat, currentMapData, messages, highlightCycle]);

  // Surface the region from the most recent query that carried one.
  const regionFromQuery = useMemo(() => {
    const withRegion = [...messages]
      .reverse()
      .find((m) => m.role === "assistant" && m.summary?.center);
    return null; // center coords exist but region label is not on response; keep null until backend exposes it
  }, [messages]);
  if (regionFromQuery && context.region === null) {
    // no-op placeholder; region kept null unless backend exposes it
  }

  // ── Filters: derive options from current markers ────────────────────────
  const availableFilterOptions = useMemo(() => {
    const nets = new Set<string>();
    const dacs = new Set<string>();
    const vars = new Set<string>();
    const statuses = new Set<string>();
    for (const m of currentMapData) {
      nets.add(m.network || "Core Argo");
      if (m.dac) dacs.add(m.dac);
      for (const v of m.variables || []) vars.add(v.toUpperCase());
      if (m.status) statuses.add(m.status);
    }
    return {
      networks: Array.from(nets).sort(),
      dacs: Array.from(dacs).sort(),
      variables: Array.from(vars).sort(),
      statuses: Array.from(statuses).sort(),
    };
  }, [currentMapData]);

  const filteredMapData = useMemo(() => {
    const { applyFilters } = require("@/lib/utils") as typeof import("@/lib/utils");
    return applyFilters(currentMapData, filters);
  }, [currentMapData, filters]);

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

  // ── Load cycle history / trajectory on explicit action ───────────────────
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
        // A trajectory response yields multiple points for one float.
        const ordered = mapData
          .filter((m) => m.float_id === floatId)
          .sort((a, b) => (a.profile_number ?? 0) - (b.profile_number ?? 0));
        const cycles: CyclePoint[] = ordered.map((m, idx) => ({
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

  // Auto-load cycles whenever a float becomes selected AND a trajectory was
  // already requested for it in the conversation. The explicit "View Trajectory"
  // action triggers loadCycleHistory directly.
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
    floatSearch,
    setFloatSearch,
    submitFloatSearch,
    loadCycleHistory,
  } as UseChatReturn;
}
