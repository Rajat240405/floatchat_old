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
import {
  sendChatMessage,
  getErrorMessage,
  getInitialRegistry,
  getFloatMetadata,
  getFloatTrajectory,
  getFloatLatestProfile,
} from "@/services/api";
import type { FloatRegistryInfo } from "@/types";
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
  /** Authoritative metadata from GET /floats/{id}/metadata (no LLM). */
  floatInfo: FloatRegistryInfo | null;
  isLoadingMetadata: boolean;

  currentMapData: MapData[];
  mode: WorkspaceMode;
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
  context: WorkspaceContext;

  cycleData: CyclePoint[] | null;
  isLoadingCycles: boolean;
  highlightCycle: number | null;
  setHighlightCycle: (n: number | null) => void;
  /** True once the user has explicitly requested trajectory for the focused float. */
  trajectoryVisible: boolean;
  showTrajectory: () => Promise<void>;
  loadLatestProfile: () => Promise<void>;

  plotItems: PlotItem[];
  plotDrawerOpen: boolean;
  setPlotDrawerOpen: (open: boolean) => void;
  togglePlotPin: (id: string) => void;
  plotFloatIds: string[];
  plotSelectedFloat: string | null;
  setPlotSelectedFloat: (id: string | null) => void;

  filters: FilterState;
  setFilters: (f: FilterState) => void;
  filteredMapData: MapData[];
  availableFilterOptions: {
    networks: string[];
    dacs: string[];
    variables: string[];
    statuses: string[];
  };
  floatCount: number;

  floatSearch: string;
  setFloatSearch: (s: string) => void;
  submitFloatSearch: () => void;
  loadCycleHistory: (floatId: string) => Promise<void>;

  isFloatFocusMode: boolean;
  clearFloatFocus: () => void;
}

/** Extract unique float IDs referenced by plotly traces (name like "Float 2903464"). */
function extractFloatIdsFromFigures(figures: PlotlyFigure[]): string[] {
  const ids = new Set<string>();
  for (const fig of figures) {
    for (const trace of fig.data || []) {
      const name = String((trace as { name?: string }).name || "");
      const m = name.match(/Float\s+(\d{5,})/i);
      if (m) ids.add(m[1]);
    }
  }
  return Array.from(ids).sort();
}

/** Detect whether a chat response targets a single float. */
function detectSingleFloatFocus(response: {
  intent?: string;
  map_data?: MapData[] | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data_summary?: any;
  figures?: PlotlyFigure[] | null;
  figure?: PlotlyFigure | null;
}): string | null {
  const summary = (response.data_summary || {}) as {
    float_info?: { float_id?: string };
    float_id?: string;
    unique_floats?: number;
  };
  const mapData = response.map_data || [];

  const floatInfo = summary.float_info;
  if (floatInfo?.float_id) return String(floatInfo.float_id);
  if (summary.float_id) return String(summary.float_id);

  if (summary.unique_floats === 1 && mapData.length >= 1) {
    return String(mapData[0].float_id);
  }

  if (mapData.length > 0) {
    const unique = new Set(mapData.map((m) => m.float_id).filter(Boolean));
    if (unique.size === 1) return String([...unique][0]);
  }

  const figs = response.figures || (response.figure ? [response.figure] : []);
  if (figs.length > 0) {
    const ids = extractFloatIdsFromFigures(figs as PlotlyFigure[]);
    if (ids.length === 1) return ids[0];
  }

  if (
    mapData.length === 1 &&
    ["metadata_lookup", "nearest_float", "trajectory", "profile_plot"].includes(
      response.intent || ""
    )
  ) {
    return String(mapData[0].float_id);
  }

  return null;
}

function markerForFloat(
  floatId: string,
  sources: MapData[][]
): MapData | null {
  for (const src of sources) {
    const hit = [...src].reverse().find((m) => m.float_id === floatId);
    if (
      hit &&
      typeof hit.latitude === "number" &&
      typeof hit.longitude === "number" &&
      !(hit.latitude === 0 && hit.longitude === 0)
    ) {
      return { ...hit, selected: false };
    }
  }
  return null;
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

  const [mode, setMode] = useState<WorkspaceMode>("chat");
  const [chatOpen, setChatOpenState] = useState(false);
  const [cycleData, setCycleData] = useState<CyclePoint[] | null>(null);
  const [isLoadingCycles, setIsLoadingCycles] = useState(false);
  const [highlightCycle, setHighlightCycle] = useState<number | null>(null);
  const [trajectoryVisible, setTrajectoryVisible] = useState(false);
  const [floatInfo, setFloatInfo] = useState<FloatRegistryInfo | null>(null);
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  const [plotItems, setPlotItems] = useState<PlotItem[]>([]);
  const [plotDrawerOpen, setPlotDrawerOpen] = useState(false);
  const [plotSelectedFloat, setPlotSelectedFloat] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [floatSearch, setFloatSearch] = useState("");

  const [initialMapData, setInitialMapData] = useState<MapData[]>([]);

  // Focus: show only this float's latest position (no trajectory until requested)
  const [focusFloatId, setFocusFloatId] = useState<string | null>(null);
  const [focusMapData, setFocusMapData] = useState<MapData[] | null>(null);
  // Multi-float query overlay
  const [queryMapData, setQueryMapData] = useState<MapData[] | null>(null);
  // Trajectory points (only drawn after explicit View Trajectory)
  const [trajectoryMapData, setTrajectoryMapData] = useState<MapData[] | null>(
    null
  );

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
        .find((m) => m.role === "assistant" && !m.isLoading && m.mapData)
        ?.mapData ?? [],
    [messages]
  );

  // Map ownership:
  //  1. Focus + trajectory visible → trajectory points
  //  2. Focus only → single latest marker
  //  3. Multi-float query overlay
  //  4. Full registry
  const currentMapData = useMemo(() => {
    if (focusFloatId) {
      if (trajectoryVisible && trajectoryMapData && trajectoryMapData.length > 0) {
        return trajectoryMapData;
      }
      if (focusMapData && focusMapData.length > 0) return focusMapData;
    }
    if (!focusFloatId && queryMapData && queryMapData.length > 0) {
      return queryMapData;
    }
    if (initialMapData.length > 0) return initialMapData;
    return chatMapData;
  }, [
    focusFloatId,
    focusMapData,
    trajectoryVisible,
    trajectoryMapData,
    queryMapData,
    chatMapData,
    initialMapData,
  ]);

  const isFloatFocusMode = Boolean(focusFloatId);

  /** Fetch trajectory/cycle points via deterministic REST — NO LLM. */
  const fetchTrajectoryData = useCallback(
    async (
      floatId: string
    ): Promise<{ cycles: CyclePoint[]; points: MapData[] }> => {
      const response = await getFloatTrajectory(floatId);
      const mapData = (response.map_data ?? []) as Array<
        MapData & {
          max_depth?: number | null;
          temp?: number | null;
          salinity?: number | null;
          has_position?: boolean;
        }
      >;

      // Keep ALL cycles returned by the API (do not drop missing coords).
      // Sort by cycle number when present, else by date.
      const ordered = [...mapData]
        .map((m) => ({ ...m, float_id: floatId }))
        .sort((a, b) => {
          const ca = a.profile_number;
          const cb = b.profile_number;
          if (ca != null && cb != null && ca !== cb) return ca - cb;
          const da = a.profile_date || "";
          const db = b.profile_date || "";
          return da.localeCompare(db);
        });

      const registryStatus =
        markerForFloat(floatId, [focusMapData || [], initialMapData])?.status ||
        ordered.find((m) => m.status && m.status !== "unknown")?.status ||
        ordered[ordered.length - 1]?.status ||
        "unknown";

      const cycles: CyclePoint[] = ordered.map((m, idx) => {
        const hasPos =
          m.has_position !== false &&
          typeof m.latitude === "number" &&
          typeof m.longitude === "number" &&
          !(m.latitude === 0 && m.longitude === 0);
        return {
          cycleNumber: m.profile_number ?? idx + 1,
          date: m.profile_date,
          latitude: hasPos ? m.latitude : null,
          longitude: hasPos ? m.longitude : null,
          variables: m.variables ?? [],
          index: idx,
          // Deployment = lowest cycle number present, not array index 0 after reverse sorts
          isDeployment: false,
          isCurrent: false,
          hasPosition: hasPos,
          maxDepth: m.max_depth ?? null,
          temp: m.temp ?? null,
          salinity: m.salinity ?? null,
        };
      });
      // Mark deployment (min cycle) and current (max cycle)
      if (cycles.length > 0) {
        const nums = cycles.map((c) => c.cycleNumber);
        const minC = Math.min(...nums);
        const maxC = Math.max(...nums);
        for (const c of cycles) {
          c.isDeployment = c.cycleNumber === minC;
          c.isCurrent = c.cycleNumber === maxC;
        }
      }

      // Map points: only those with valid coordinates
      const points: MapData[] = ordered
        .filter((m) => {
          const hasPos =
            m.has_position !== false &&
            typeof m.latitude === "number" &&
            typeof m.longitude === "number" &&
            !(m.latitude === 0 && m.longitude === 0);
          return hasPos;
        })
        .map((m, idx, arr) => ({
          ...m,
          status: registryStatus,
          selected: idx === arr.length - 1,
        }));
      return { cycles, points };
    },
    [focusMapData, initialMapData]
  );

  /** Load cycle history table only — deterministic REST, no map draw. */
  const loadCycleHistory = useCallback(
    async (floatId: string) => {
      if (isLoadingCycles) return;
      setIsLoadingCycles(true);
      try {
        const { cycles } = await fetchTrajectoryData(floatId);
        setCycleData(cycles.length > 0 ? cycles : null);
        setHighlightCycle(null);
      } catch {
        setCycleData(null);
      } finally {
        setIsLoadingCycles(false);
      }
    },
    [isLoadingCycles, fetchTrajectoryData]
  );

  /** Explicit View Trajectory — deterministic REST, draw path on map. */
  const showTrajectory = useCallback(async () => {
    const floatId = focusFloatId || selectedFloat;
    if (!floatId || isLoadingCycles) return;
    setIsLoadingCycles(true);
    try {
      const { cycles, points } = await fetchTrajectoryData(floatId);
      setCycleData(cycles.length > 0 ? cycles : null);
      if (points.length > 0) {
        setTrajectoryMapData(points);
        setTrajectoryVisible(true);
      }
      setHighlightCycle(null);
    } catch {
      /* keep prior state */
    } finally {
      setIsLoadingCycles(false);
    }
  }, [focusFloatId, selectedFloat, isLoadingCycles, fetchTrajectoryData]);

  /** Show Latest Profile — deterministic REST, opens plot drawer. No LLM. */
  const loadLatestProfile = useCallback(async () => {
    const floatId = focusFloatId || selectedFloat;
    if (!floatId || isLoading) return;
    setIsLoading(true);
    try {
      const response = await getFloatLatestProfile(floatId);
      const figures = response.figures ?? (response.figure ? [response.figure] : []);
      if (figures.length > 0) {
        setPlotItems(
          figures.map((f, i) => ({
            id: `latest-${floatId}-${i}-${f.variable ?? "var"}`,
            variable: f.variable ?? `var${i + 1}`,
            title: f.variable ? String(f.variable) : `Plot ${i + 1}`,
            figure: f,
            pinned: false,
          }))
        );
        const ids = extractFloatIdsFromFigures(figures);
        setPlotSelectedFloat(ids.length >= 1 ? ids[0] : floatId);
        setPlotDrawerOpen(true);
      }
    } catch (e) {
      console.warn("Latest profile failed", e);
    } finally {
      setIsLoading(false);
    }
  }, [focusFloatId, selectedFloat, isLoading]);

  /** Load authoritative metadata via REST — NO LLM. */
  const loadFloatMetadata = useCallback(async (floatId: string) => {
    setIsLoadingMetadata(true);
    // Clear previous float so the marker stub cannot flash wrong dates
    setFloatInfo(null);
    try {
      const resp = await getFloatMetadata(floatId);
      const info = resp.float_info || null;
      // Normalize empty strings so the UI can show "Not Available"
      if (info) {
        const blank = (v: unknown) =>
          v == null || v === "" || v === "unknown" || v === "None" || v === "nan";
        if (blank(info.platform_type)) info.platform_type = "";
        if (blank(info.profiler_type)) info.profiler_type = "";
        if (blank(info.manufacturer)) info.manufacturer = "";
        if (blank(info.institution)) info.institution = "";
        if (blank(info.dac)) info.dac = "";
      }
      setFloatInfo(info);
      // Enrich focus marker from metadata position if we only had a stub
      if (resp.map_data && resp.map_data.length > 0) {
        setFocusMapData((prev) => {
          if (prev && prev.length > 0) {
            const base = prev[prev.length - 1];
            const m = resp.map_data[0];
            return [
              {
                ...base,
                ...m,
                float_id: floatId,
                selected: true,
                status: m.status || base.status || "unknown",
              },
            ];
          }
          return resp.map_data.map((m) => ({ ...m, selected: true }));
        });
      }
    } catch (e) {
      console.warn("Metadata lookup failed", e);
      setFloatInfo(null);
    } finally {
      setIsLoadingMetadata(false);
    }
  }, []);

  /**
   * Pin a single float on the map (latest position only).
   * Does NOT open metadata or load cycles — that happens on marker click.
   */
  const pinFloatOnMap = useCallback(
    (floatId: string, markers?: MapData[]) => {
      setFocusFloatId(floatId);
      setQueryMapData(null);
      setTrajectoryVisible(false);
      setTrajectoryMapData(null);
      setHighlightCycle(null);
      // Do not auto-select / open metadata
      setSelectedFloat(null);
      setMode("chat");
      setCycleData(null);
      setChatOpenState(false);

      const fromMarkers =
        markers && markers.length > 0
          ? markers.filter((m) => m.float_id === floatId)
          : [];
      const single =
        markerForFloat(floatId, [fromMarkers, chatMapData, initialMapData]) ||
        (fromMarkers[0]
          ? { ...fromMarkers[fromMarkers.length - 1], selected: false }
          : null);

      if (single) {
        setFocusMapData([{ ...single, selected: false }]);
      } else {
        // Keep a placeholder so focus mode is active; coords may arrive later
        setFocusMapData([]);
      }
    },
    [chatMapData, initialMapData]
  );

  /**
   * User clicked a float marker → open Metadata + load Cycle History table.
   * Trajectory is NOT drawn until View Trajectory is clicked.
   */
  const openFloatInspector = useCallback(
    async (floatId: string) => {
      setFocusFloatId(floatId);
      setSelectedFloat(floatId);
      setMode("metadata");
      setChatOpenState(false);
      setHighlightCycle(null);
      setTrajectoryVisible(false);
      setTrajectoryMapData(null);
      setQueryMapData(null);

      const single = markerForFloat(floatId, [
        focusMapData || [],
        trajectoryMapData || [],
        queryMapData || [],
        chatMapData,
        initialMapData,
      ]);
      if (single) {
        setFocusMapData([{ ...single, selected: true }]);
      }

      // Deterministic REST — metadata + cycles in parallel, no LLM
      await Promise.all([
        loadFloatMetadata(floatId),
        loadCycleHistory(floatId),
      ]);
    },
    [
      focusMapData,
      trajectoryMapData,
      queryMapData,
      chatMapData,
      initialMapData,
      loadCycleHistory,
      loadFloatMetadata,
    ]
  );

  const clearFloatFocus = useCallback(() => {
    setFocusFloatId(null);
    setFocusMapData(null);
    setQueryMapData(null);
    setTrajectoryVisible(false);
    setTrajectoryMapData(null);
    setSelectedFloat(null);
    setFloatInfo(null);
    setMode("chat");
    setChatOpenState(false);
    setCycleData(null);
    setHighlightCycle(null);
  }, []);

  // Marker click handler
  const handleSelectFloat = useCallback(
    async (floatId: string | null) => {
      if (!floatId) {
        // Deselect inspector but keep a single-float pin so user can re-click
        if (selectedFloat && focusFloatId) {
          setSelectedFloat(null);
          setFloatInfo(null);
          setMode("chat");
          setCycleData(null);
          setHighlightCycle(null);
          setTrajectoryVisible(false);
          setTrajectoryMapData(null);
          if (focusMapData) {
            setFocusMapData(
              focusMapData.map((m) => ({ ...m, selected: false }))
            );
          }
          return;
        }
        // Empty-map click with no selection → restore full registry
        // (natural transition; no floating Dashboard control needed)
        clearFloatFocus();
        return;
      }
      await openFloatInspector(floatId);
    },
    [selectedFloat, focusFloatId, focusMapData, clearFloatFocus, openFloatInspector]
  );

  const setChatOpen = useCallback((open: boolean) => {
    setChatOpenState(open);
  }, []);

  const context: WorkspaceContext = useMemo(() => {
    const sel = selectedFloat
      ? currentMapData.find((m) => m.float_id === selectedFloat)
      : undefined;
    const cyclePoint =
      highlightCycle != null && cycleData
        ? cycleData.find((c) => c.cycleNumber === highlightCycle)
        : undefined;
    return {
      floatId: selectedFloat,
      cycle: highlightCycle,
      region: null,
      variables: cyclePoint?.variables ?? sel?.variables ?? [],
    };
  }, [selectedFloat, currentMapData, highlightCycle, cycleData]);

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
    const result = {
      networks: Array.from(nets).sort(),
      dacs: Array.from(dacs).sort(),
      variables: Array.from(vars).sort(),
      statuses: Array.from(statuses).sort(),
    };
    if (result.networks.length === 0) result.networks = ["Core Argo", "BGC Argo"];
    if (result.dacs.length === 0) result.dacs = ["INCOIS", "Coriolis", "AOML"];
    if (result.variables.length === 0)
      result.variables = ["TEMP", "PSAL", "DOXY", "CHLA"];
    if (result.statuses.length === 0)
      result.statuses = ["active", "inactive", "drifted"];
    return result;
  }, [sourceDataForFilters]);

  const filteredMapData = useMemo(() => {
    return applyFilters(currentMapData, filters);
  }, [currentMapData, filters]);

  const totalFloatCount = useMemo(() => {
    const ids = new Set(filteredMapData.map((m) => m.float_id));
    return ids.size;
  }, [filteredMapData]);

  const bootstrapInitialRegistry = useCallback(async () => {
    try {
      const resp = await getInitialRegistry();
      const data = (resp.map_data || []) as MapData[];
      if (Array.isArray(data) && data.length > 0) {
        setInitialMapData(data);
      }
    } catch (e) {
      console.warn("Initial registry bootstrap failed", e);
    }
  }, []);

  useEffect(() => {
    bootstrapInitialRegistry();
  }, [bootstrapInitialRegistry]);

  const plotFloatIds = useMemo(() => {
    const figs = plotItems.map((p) => p.figure);
    return extractFloatIdsFromFigures(figs);
  }, [plotItems]);

  const sendMessage = useCallback(
    async (customText?: string) => {
      const queryText = (customText ?? input).trim();
      if (!queryText || isLoading) return;

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
        const effectiveFigures: PlotlyFigure[] =
          figures && figures.length > 0
            ? figures
            : response.figure
              ? [
                  {
                    ...response.figure,
                    variable: response.figure.variable || "plot",
                  },
                ]
              : [];

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessage.id
              ? {
                  ...msg,
                  content: response.message,
                  figure: response.figure,
                  figures: effectiveFigures.length > 0 ? effectiveFigures : null,
                  summary: response.data_summary,
                  intent: response.intent,
                  mapData: response.map_data,
                  isLoading: false,
                }
              : msg
          )
        );

        if (effectiveFigures.length > 0) {
          setPlotItems(
            effectiveFigures.map((f, i) => ({
              id: `${response.intent || "plot"}-${i}-${f.variable ?? "var"}`,
              variable: f.variable ?? `var${i + 1}`,
              title: f.variable
                ? String(f.variable)
                : ((f.layout as { title?: { text?: string } | string })?.title &&
                    (typeof (f.layout as { title?: unknown }).title === "string"
                      ? (f.layout as { title: string }).title
                      : (f.layout as { title?: { text?: string } }).title
                          ?.text)) ||
                  `Plot ${i + 1}`,
              figure: f,
              pinned: false,
            }))
          );
          const ids = extractFloatIdsFromFigures(effectiveFigures);
          setPlotSelectedFloat(ids.length >= 1 ? ids[0] : null);
          setPlotDrawerOpen(true);
        }

        const singleId = detectSingleFloatFocus(response);
        const mapData = response.map_data || [];
        const intent = response.intent || "";

        // Explicit trajectory chat response: respect and draw
        if (intent === "trajectory" && singleId) {
          setFocusFloatId(singleId);
          setQueryMapData(null);
          const ordered = mapData
            .filter((m) => m.float_id === singleId)
            .sort(
              (a, b) => (a.profile_number ?? 0) - (b.profile_number ?? 0)
            );
          if (ordered.length > 0) {
            setTrajectoryMapData(
              ordered.map((m, idx) => ({
                ...m,
                selected: idx === ordered.length - 1,
              }))
            );
            setTrajectoryVisible(true);
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
              }))
            );
          }
          // If already inspecting this float, keep metadata open
          if (selectedFloat === singleId) {
            setMode("metadata");
          } else {
            // Pin only — user can click marker for metadata
            setSelectedFloat(null);
            setMode("chat");
            const latest = ordered[ordered.length - 1];
            if (latest) setFocusMapData([{ ...latest, selected: false }]);
          }
        } else if (singleId) {
          // Single-float search/profile: pin on map ONLY. No auto metadata/cycles/trajectory.
          pinFloatOnMap(singleId, mapData);
        } else {
          // Multi-float / region / knowledge
          setFocusFloatId(null);
          setFocusMapData(null);
          setTrajectoryVisible(false);
          setTrajectoryMapData(null);
          setSelectedFloat(null);
          setMode("chat");
          setCycleData(null);
          setHighlightCycle(null);

          const unique = new Set(mapData.map((m) => m.float_id).filter(Boolean));
          if (unique.size > 1) {
            setQueryMapData(mapData);
          } else if (mapData.length === 0) {
            setQueryMapData(null);
          } else {
            setQueryMapData(mapData);
          }
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
    [input, isLoading, pinFloatOnMap, selectedFloat]
  );

  const togglePlotPin = useCallback((id: string) => {
    setPlotItems((prev) =>
      prev.map((p) => (p.id === id ? { ...p, pinned: !p.pinned } : p))
    );
  }, []);

  const submitFloatSearch = useCallback(() => {
    const raw = floatSearch.trim();
    if (!raw) return;
    const fid = raw.replace(/\D/g, "");
    if (!fid) return;
    // Deterministic dashboard navigation — NO chat, NO LLM
    openFloatInspector(fid);
  }, [floatSearch, openFloatInspector]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    },
    [sendMessage]
  );

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
    floatInfo,
    isLoadingMetadata,
    currentMapData,
    mode,
    chatOpen,
    setChatOpen,
    context,
    cycleData,
    isLoadingCycles,
    highlightCycle,
    setHighlightCycle,
    trajectoryVisible,
    showTrajectory,
    loadLatestProfile,
    plotItems,
    plotDrawerOpen,
    setPlotDrawerOpen,
    togglePlotPin,
    plotFloatIds,
    plotSelectedFloat,
    setPlotSelectedFloat,
    filters,
    setFilters,
    filteredMapData,
    availableFilterOptions,
    floatCount: totalFloatCount,
    floatSearch,
    setFloatSearch,
    submitFloatSearch,
    loadCycleHistory,
    isFloatFocusMode,
    clearFloatFocus,
  } as UseChatReturn;
}
