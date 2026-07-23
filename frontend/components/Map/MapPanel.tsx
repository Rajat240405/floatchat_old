"use client";

import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import Map, { NavigationControl, Source, Layer, Popup } from "react-map-gl/maplibre";
import { motion, AnimatePresence } from "framer-motion";
import { Globe, Crosshair, X, Factory } from "lucide-react";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapData } from "@/types";
import { formatDate, formatLat, formatLon } from "@/lib/utils";

interface MapPanelProps {
  mapData: MapData[];
  selectedFloat: string | null;
  onSelectFloat: (floatId: string | null) => void;
  onDrillDown?: (query: string) => void;
  radiusCenter?: { lat: number; lon: number } | null;
  radiusKm?: number | null;
  focusMode?: boolean;
  /** True when trajectory path/points are actively drawn. */
  trajectoryVisible?: boolean;
  /** Cycle number highlighted from table or map. */
  highlightedCycle?: number | null;
  /** Called when user clicks a trajectory profile point. */
  onSelectTrajectoryPoint?: (cycleNumber: number | null) => void;
}

const MAP_STYLE: any = {
  version: 8,
  sources: {
    esriOcean: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "© Esri, GEBCO, NOAA, National Geographic",
    },
  },
  layers: [
    {
      id: "esri-ocean-raster",
      type: "raster",
      source: "esriOcean",
    },
  ],
};

function buildRadiusGeoJSON(lat: number, lon: number, radiusKm: number) {
  const points = 64;
  const earthR = 6371;
  const coords: [number, number][] = [];
  for (let i = 0; i <= points; i++) {
    const angle = (i / points) * 2 * Math.PI;
    const dLat = (radiusKm / earthR) * (180 / Math.PI) * Math.cos(angle);
    const dLon =
      ((radiusKm / earthR) * (180 / Math.PI) * Math.sin(angle)) /
      Math.cos((lat * Math.PI) / 180);
    coords.push([lon + dLon, lat + dLat]);
  }
  return {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        geometry: { type: "Polygon" as const, coordinates: [coords] },
        properties: {},
      },
    ],
  };
}

export function MapPanel({
  mapData,
  selectedFloat,
  onSelectFloat,
  radiusCenter,
  radiusKm,
  focusMode = false,
  trajectoryVisible = false,
  highlightedCycle = null,
  onSelectTrajectoryPoint,
}: MapPanelProps) {
  const uniqueFloatIds = useMemo(
    () => new Set(mapData.map((m) => m.float_id).filter(Boolean)),
    [mapData]
  );
  const markerCount = uniqueFloatIds.size;
  const pointCount = mapData.length;
  const isTrajectoryMode = trajectoryVisible && pointCount > 1;

  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [viewState, setViewState] = useState({
    longitude: 75.0,
    latitude: 12.0,
    zoom: 3.8,
  });
  const mapRef = useRef<any>(null);
  const prevDataSignatureRef = useRef<string>("");

  // Auto-zoom
  useEffect(() => {
    if (!mapData || mapData.length === 0) return;

    const signature = `${focusMode ? "F" : "R"}_${trajectoryVisible ? "T" : "P"}_${mapData.length}_${mapData[0]?.float_id}_${mapData[0]?.latitude}_${mapData[0]?.longitude}`;
    if (signature === prevDataSignatureRef.current) return;
    prevDataSignatureRef.current = signature;

    const lats = mapData
      .map((m) => m.latitude)
      .filter((n) => typeof n === "number" && !isNaN(n) && n !== 0);
    const lons = mapData
      .map((m) => m.longitude)
      .filter((n) => typeof n === "number" && !isNaN(n));
    if (lats.length === 0 || lons.length === 0) return;

    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const centerLat = (minLat + maxLat) / 2;
    const centerLon = (minLon + maxLon) / 2;
    const spanLat = maxLat - minLat;
    const spanLon = maxLon - minLon;
    const maxSpan = Math.max(spanLat, spanLon);

    let zoom = 4.0;
    if (focusMode || uniqueFloatIds.size === 1) {
      if (pointCount === 1 || maxSpan < 0.02) zoom = 6.5;
      else if (maxSpan < 0.5) zoom = 7.5;
      else if (maxSpan < 2.0) zoom = 6.5;
      else if (maxSpan < 5.0) zoom = 5.8;
      else if (maxSpan < 12.0) zoom = 5.0;
      else zoom = 4.2;
    } else if (mapData.length === 1 || maxSpan < 0.02) zoom = 7.5;
    else if (maxSpan < 0.1) zoom = 10.0;
    else if (maxSpan < 0.5) zoom = 8.5;
    else if (maxSpan < 2.0) zoom = 7.0;
    else if (maxSpan < 5.0) zoom = 6.0;
    else if (maxSpan < 12.0) zoom = 5.0;
    else if (maxSpan < 25.0) zoom = 4.2;
    else zoom = 3.5;

    setViewState({ longitude: centerLon, latitude: centerLat, zoom });
  }, [mapData, focusMode, trajectoryVisible, uniqueFloatIds.size, pointCount]);

  // Active popup: highlighted cycle point (trajectory) or selected float marker
  const activePoint = useMemo(() => {
    if (isTrajectoryMode && highlightedCycle != null) {
      return (
        mapData.find((m) => m.profile_number === highlightedCycle) || null
      );
    }
    if (selectedFloat && !isTrajectoryMode) {
      return (
        [...mapData].reverse().find((m) => m.float_id === selectedFloat) || null
      );
    }
    return null;
  }, [isTrajectoryMode, highlightedCycle, selectedFloat, mapData]);

  const hoveredPoint = useMemo(() => {
    if (!hoveredKey) return null;
    // key = floatId or floatId:cycle
    if (hoveredKey.includes(":")) {
      const [fid, cyc] = hoveredKey.split(":");
      return (
        mapData.find(
          (m) =>
            m.float_id === fid && String(m.profile_number ?? "") === cyc
        ) || null
      );
    }
    return mapData.find((m) => m.float_id === hoveredKey) || null;
  }, [hoveredKey, mapData]);

  // GeoJSON markers
  const markersGeoJSON = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: mapData
        .filter((d) => {
          // Skip invalid / placeholder coordinates
          if (typeof d.latitude !== "number" || typeof d.longitude !== "number")
            return false;
          if (!isFinite(d.latitude) || !isFinite(d.longitude)) return false;
          if (d.latitude === 0 && d.longitude === 0) return false;
          return true;
        })
        .map((d, idx) => {
        const cycle = d.profile_number ?? idx + 1;
        const isHighlighted =
          isTrajectoryMode &&
          highlightedCycle != null &&
          d.profile_number === highlightedCycle;
        const isSelectedFloat =
          !isTrajectoryMode &&
          (d.float_id === selectedFloat || !!d.selected);
        const pcRaw = (d as { profile_count?: number | null }).profile_count;
        const pc =
          typeof pcRaw === "number" && isFinite(pcRaw) ? Math.max(0, pcRaw) : 0;
        // Continuous radius from profile_count: ~5px (few) → ~14px (100+).
        const sizeFromCount = Math.min(
          14,
          Math.max(5, 4.5 + Math.sqrt(Math.max(pc, 1)) * 0.95)
        );
        return {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: [d.longitude, d.latitude],
          },
          properties: {
            float_id: d.float_id,
            profile_number: cycle,
            profile_count: pc,
            marker_size: isTrajectoryMode ? 6 : sizeFromCount,
            status: d.status || "unknown",
            dac: d.dac || "",
            profile_date: d.profile_date || "",
            selected: isSelectedFloat || isHighlighted,
            hovered:
              hoveredKey === d.float_id ||
              hoveredKey === `${d.float_id}:${cycle}`,
            // Exploration: dim every non-selected float when one is selected
            dimmed:
              !isTrajectoryMode &&
              !!selectedFloat &&
              d.float_id !== selectedFloat,
            is_trajectory_point: isTrajectoryMode,
          },
        };
      }),
    }),
    [mapData, selectedFloat, hoveredKey, isTrajectoryMode, highlightedCycle]
  );

  const trajectoryGeoJSON = useMemo(() => {
    if (!isTrajectoryMode) {
      return { type: "FeatureCollection" as const, features: [] as any[] };
    }
    const grouped: Record<
      string,
      { path: [number, number][]; status?: string }
    > = {};
    for (const d of mapData) {
      if (!grouped[d.float_id])
        grouped[d.float_id] = { path: [], status: d.status };
      if (typeof d.longitude === "number" && typeof d.latitude === "number") {
        grouped[d.float_id].path.push([d.longitude, d.latitude]);
      }
    }
    return {
      type: "FeatureCollection" as const,
      features: Object.entries(grouped)
        .filter(([, g]) => g.path.length >= 2)
        .map(([float_id, g]) => ({
          type: "Feature" as const,
          geometry: { type: "LineString" as const, coordinates: g.path },
          properties: { float_id, status: g.status || "unknown" },
        })),
    };
  }, [mapData, isTrajectoryMode]);

  const radiusGeoJSON = useMemo(() => {
    if (!radiusCenter || !radiusKm) return null;
    return buildRadiusGeoJSON(radiusCenter.lat, radiusCenter.lon, radiusKm);
  }, [radiusCenter, radiusKm]);

  const radiusFillLayer = {
    id: "radius-fill",
    type: "fill" as const,
    paint: { "fill-color": "#0284c7", "fill-opacity": 0.08 },
  };
  const radiusLineLayer = {
    id: "radius-line",
    type: "line" as const,
    paint: { "line-color": "#0284c7", "line-width": 2, "line-opacity": 0.7 },
  };

  const trajectoryLayer = {
    id: "trajectories",
    type: "line" as const,
    paint: {
      "line-color": [
        "match",
        ["get", "status"],
        "active",
        "#00d2ff",
        "drifted",
        "#ffa01e",
        "inactive",
        "#ff5050",
        "#00d2ff",
      ] as any,
      "line-width": 2.5,
      "line-opacity": 0.85,
    },
  };

  const markerHaloLayer = {
    id: "marker-halo",
    type: "circle" as const,
    filter: ["==", ["get", "selected"], true] as any,
    paint: {
      "circle-radius": [
        "+",
        ["coalesce", ["get", "marker_size"], 7],
        6,
      ] as any,
      "circle-color": "transparent",
      "circle-stroke-width": 3,
      "circle-stroke-color": "#38bdf8",
    },
  };

  // Status colors from registry; radius from profile_count (marker_size).
  const markerLayer = {
    id: "float-markers",
    type: "circle" as const,
    paint: {
      "circle-radius": [
        "case",
        ["==", ["get", "selected"], true],
        ["+", ["coalesce", ["get", "marker_size"], 7], 2.5],
        ["==", ["get", "hovered"], true],
        ["+", ["coalesce", ["get", "marker_size"], 7], 1.5],
        ["coalesce", ["get", "marker_size"], 7],
      ] as any,
      "circle-color": [
        "case",
        ["==", ["get", "selected"], true],
        "#06b6d4",
        [
          "match",
          ["get", "status"],
          "active",
          "#00d2ff",
          "drifted",
          "#ffa01e",
          "inactive",
          "#ff5050",
          "#94a3b8",
        ],
      ] as any,
      "circle-stroke-width": [
        "case",
        ["==", ["get", "selected"], true],
        2.5,
        ["==", ["get", "dimmed"], true],
        1,
        1.5,
      ] as any,
      "circle-stroke-color": "#ffffff",
      "circle-opacity": [
        "case",
        ["==", ["get", "dimmed"], true],
        0.28,
        ["==", ["get", "selected"], true],
        1,
        0.92,
      ] as any,
    },
  };

  const onMapClick = useCallback(
    (e: any) => {
      const features = e.features ?? [];
      const f = features.find((ft: any) => ft.layer?.id === "float-markers");
      if (f) {
        const fid = f.properties?.float_id as string;
        const cycleRaw = f.properties?.profile_number;
        const cycle =
          cycleRaw != null && cycleRaw !== ""
            ? Number(cycleRaw)
            : null;

        if (isTrajectoryMode && onSelectTrajectoryPoint && cycle != null) {
          // Clicking a trajectory point → sync cycle table
          onSelectTrajectoryPoint(
            highlightedCycle === cycle ? null : cycle
          );
          return;
        }

        // Normal marker click → open inspector (or toggle off)
        onSelectFloat(fid === selectedFloat ? null : fid);
      } else {
        if (isTrajectoryMode && onSelectTrajectoryPoint) {
          onSelectTrajectoryPoint(null);
        } else {
          onSelectFloat(null);
        }
      }
    },
    [
      selectedFloat,
      onSelectFloat,
      isTrajectoryMode,
      onSelectTrajectoryPoint,
      highlightedCycle,
    ]
  );

  const onMouseMove = useCallback(
    (e: any) => {
      const features = e.features ?? [];
      const f = features.find((ft: any) => ft.layer?.id === "float-markers");
      if (f) {
        const fid = f.properties?.float_id as string;
        const cycle = f.properties?.profile_number;
        setHoveredKey(
          isTrajectoryMode && cycle != null ? `${fid}:${cycle}` : fid
        );
        if (mapRef.current) {
          mapRef.current.getCanvas().style.cursor = "pointer";
        }
      } else {
        setHoveredKey(null);
        if (mapRef.current) {
          mapRef.current.getCanvas().style.cursor = "";
        }
      }
    },
    [isTrajectoryMode]
  );

  const onMouseLeave = useCallback(() => {
    setHoveredKey(null);
    if (mapRef.current) {
      mapRef.current.getCanvas().style.cursor = "";
    }
  }, []);

  const statusColorClass = (status?: string | null) => {
    if (status === "active") return "text-emerald-600";
    if (status === "drifted") return "text-amber-600";
    if (status === "inactive") return "text-red-500";
    return "text-slate-500";
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.6 }}
      className="relative h-full bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden shadow-lg"
    >
      <div className="absolute top-3 left-4 z-[400] flex items-center gap-2 px-3.5 py-2 bg-slate-900/90 backdrop-blur-md border border-slate-700/60 rounded-xl shadow-lg pointer-events-none">
        <Globe className="w-4 h-4 text-ocean-400" />
        <span className="text-xs font-semibold text-slate-100 tracking-tight">
          {isTrajectoryMode
            ? "Analysis · Trajectory"
            : selectedFloat
              ? "Exploration · Float selected"
              : focusMode
                ? "Exploration"
                : "India Region Dashboard"}
        </span>
        {markerCount > 0 && (
          <span className="ml-1.5 text-[11px] px-2 py-0.5 rounded-md bg-ocean-500/15 text-ocean-300 font-semibold border border-ocean-500/30">
            {markerCount} float{markerCount !== 1 ? "s" : ""}
            {isTrajectoryMode ? ` · ${pointCount} pts` : ""}
          </span>
        )}
      </div>

      {selectedFloat && (
        <div className="absolute top-16 left-4 z-[400] flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-ocean-700/50 backdrop-blur-md shadow-lg text-ocean-200">
          <Crosshair className="w-3.5 h-3.5 text-ocean-400 animate-pulse" />
          <span className="text-xs font-semibold text-ocean-200 tracking-tight">
            Selected: Float {selectedFloat}
            {highlightedCycle != null ? ` · Cycle #${highlightedCycle}` : ""}
          </span>
          <button
            onClick={() => {
              onSelectTrajectoryPoint?.(null);
              onSelectFloat(null);
            }}
            className="ml-1 text-ocean-400 hover:text-ocean-200 text-xs font-bold px-1.5 py-0.5 rounded hover:bg-ocean-800/60 transition-colors cursor-pointer"
            title="Clear selection"
          >
            ✕
          </button>
        </div>
      )}

      <Map
        ref={mapRef}
        {...viewState}
        onMove={(e) => setViewState(e.viewState)}
        mapStyle={MAP_STYLE}
        style={{ width: "100%", height: "100%" }}
        minZoom={2.5}
        maxZoom={12}
        interactiveLayerIds={["float-markers"]}
        onClick={onMapClick}
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseLeave}
      >
        <NavigationControl position="bottom-right" />

        {radiusGeoJSON && (
          <Source id="radius" type="geojson" data={radiusGeoJSON}>
            <Layer {...radiusFillLayer} />
            <Layer {...radiusLineLayer} />
          </Source>
        )}

        {trajectoryGeoJSON.features.length > 0 && (
          <Source id="trajectories" type="geojson" data={trajectoryGeoJSON}>
            <Layer {...trajectoryLayer} />
          </Source>
        )}

        {markersGeoJSON.features.length > 0 && (
          <Source id="float-markers" type="geojson" data={markersGeoJSON}>
            <Layer {...markerHaloLayer} />
            <Layer {...markerLayer} />
          </Source>
        )}

        {/* Hover popup (when not showing a selected cycle card) */}
        {hoveredPoint && !activePoint && (
          <Popup
            longitude={hoveredPoint.longitude}
            latitude={hoveredPoint.latitude}
            closeButton={false}
            closeOnClick={false}
            anchor="bottom"
            offset={14}
          >
            <div className="text-xs font-sans p-1.5 min-w-[140px]">
              <div className="font-bold text-slate-800">
                Float {hoveredPoint.float_id}
              </div>
              {isTrajectoryMode && hoveredPoint.profile_number != null && (
                <div className="text-slate-600 font-semibold">
                  Cycle #{hoveredPoint.profile_number}
                </div>
              )}
              {hoveredPoint.profile_date && (
                <div className="text-slate-500">
                  {formatDate(hoveredPoint.profile_date)}
                </div>
              )}
              {!isTrajectoryMode && (
                <div
                  className={`font-semibold capitalize ${statusColorClass(
                    hoveredPoint.status
                  )}`}
                >
                  {hoveredPoint.status || "unknown"}
                </div>
              )}
            </div>
          </Popup>
        )}
      </Map>

      {/* Trajectory point card — shown when a cycle is highlighted */}
      <AnimatePresence>
        {isTrajectoryMode && activePoint && (
          <motion.div
            key={`cycle-${activePoint.float_id}-${activePoint.profile_number}`}
            initial={{ opacity: 0, scale: 0.92, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="absolute bottom-12 left-4 z-[900] w-[280px] pointer-events-auto"
          >
            <div className="bg-slate-900/98 backdrop-blur-xl rounded-2xl shadow-2xl border border-slate-700/50 p-4 text-slate-100 font-sans">
              <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-slate-700/40">
                <div>
                  <span className="text-sm font-extrabold text-slate-50 block">
                    Float {activePoint.float_id}
                  </span>
                  <span className="text-xs font-semibold text-ocean-300">
                    Cycle #{activePoint.profile_number ?? "—"}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => onSelectTrajectoryPoint?.(null)}
                  className="w-6 h-6 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-700/60 cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="grid grid-cols-1 gap-2 pt-3 text-xs">
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">
                    Profile Date
                  </span>
                  <span className="font-bold text-slate-200">
                    {formatDate(activePoint.profile_date)}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">
                      Latitude
                    </span>
                    <span className="font-bold text-slate-200 font-mono">
                      {formatLat(activePoint.latitude)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">
                      Longitude
                    </span>
                    <span className="font-bold text-slate-200 font-mono">
                      {formatLon(activePoint.longitude)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Non-trajectory selected float card (compact) */}
      <AnimatePresence>
        {!isTrajectoryMode && activePoint && selectedFloat && (
          <motion.div
            key={`float-${activePoint.float_id}`}
            initial={{ opacity: 0, scale: 0.92, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="absolute bottom-12 left-4 z-[900] w-[280px] pointer-events-auto"
          >
            <div className="bg-slate-900/98 backdrop-blur-xl rounded-2xl shadow-2xl border border-slate-700/50 p-4 text-slate-100 font-sans">
              <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-slate-700/40">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-8 h-8 rounded-lg bg-ocean-500/15 border border-ocean-500/30 flex items-center justify-center">
                    <Globe className="w-4 h-4 text-ocean-400" />
                  </div>
                  <div className="min-w-0">
                    <span className="text-sm font-extrabold text-slate-50 block truncate">
                      Float {activePoint.float_id}
                    </span>
                    {activePoint.manufacturer && (
                      <span className="text-[10px] font-medium text-ocean-300/80 flex items-center gap-1">
                        <Factory className="w-3 h-3" />
                        {activePoint.manufacturer}
                      </span>
                    )}
                  </div>
                </div>
                {activePoint.status && (
                  <span
                    className={`flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border capitalize shrink-0 ${
                      activePoint.status === "active"
                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                        : activePoint.status === "drifted"
                          ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                          : "bg-slate-700/50 text-slate-400 border-slate-600/50"
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        activePoint.status === "active"
                          ? "bg-emerald-400 animate-pulse"
                          : activePoint.status === "drifted"
                            ? "bg-amber-400"
                            : "bg-slate-500"
                      }`}
                    />
                    {activePoint.status}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2 pt-3 text-xs">
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">
                    DAC
                  </span>
                  <span className="font-bold text-slate-200 uppercase">
                    {activePoint.dac || "N/A"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">
                    Last Report
                  </span>
                  <span className="font-bold text-slate-200">
                    {formatDate(activePoint.profile_date)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">
                    Latitude
                  </span>
                  <span className="font-bold text-slate-200">
                    {formatLat(activePoint.latitude)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">
                    Longitude
                  </span>
                  <span className="font-bold text-slate-200">
                    {formatLon(activePoint.longitude)}
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
