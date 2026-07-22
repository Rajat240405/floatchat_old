"use client";

import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer, PathLayer } from "@deck.gl/layers";
import { Map, NavigationControl } from "react-map-gl/maplibre";
import { WebMercatorViewport } from "@deck.gl/core";
import { motion, AnimatePresence } from "framer-motion";
import { Globe, Crosshair, X, Battery, Factory } from "lucide-react";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapData } from "@/types";

interface MapPanelProps {
  mapData: MapData[];
  selectedFloat: string | null;
  onSelectFloat: (floatId: string | null) => void;
  onDrillDown?: (query: string) => void;
  radiusCenter?: { lat: number; lon: number } | null;
  radiusKm?: number | null;
}

const MAP_STYLE = {
  version: 8,
  sources: {
    esri: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
      ],
      tileSize: 256,
      attribution:
        "Tiles © Esri, Maxar, Earthstar Geographics"
    }
  },
  layers: [
    {
      id: "esri-imagery",
      type: "raster",
      source: "esri"
    }
  ]
};

export function MapPanel({
  mapData,
  selectedFloat,
  onSelectFloat,
  onDrillDown,
  radiusCenter,
  radiusKm,
}: MapPanelProps) {
  const markerCount = mapData.length;
  const [hoveredFloat, setHoveredFloat] = useState<string | null>(null);
  const [showAllSensors, setShowAllSensors] = useState<boolean>(false);
  const [viewState, setViewState] = useState({
    longitude: 75.0,
    latitude: 15.0,
    zoom: 4,
    pitch: 0,
    bearing: 0,
  });
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerSize, setContainerSize] = useState({ width: 800, height: 600 });

  const prevDataSignatureRef = useRef<string>("");

  useEffect(() => {
    if (!selectedFloat) {
      setShowAllSensors(false);
    }
  }, [selectedFloat]);

  // Track container size for popup positioning
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const selectedMarker = useMemo(() => {
    if (!selectedFloat || !mapData) return null;
    return (
      [...mapData].reverse().find((m) => m.float_id === selectedFloat) || null
    );
  }, [selectedFloat, mapData]);

  // Project selected marker lat/lon to screen x,y using WebMercatorViewport
  const popupPosition = useMemo(() => {
    if (!selectedMarker) return null;
    try {
      const viewport = new WebMercatorViewport({
        width: containerSize.width,
        height: containerSize.height,
        longitude: viewState.longitude,
        latitude: viewState.latitude,
        zoom: viewState.zoom,
        pitch: viewState.pitch,
        bearing: viewState.bearing,
      });
      const [x, y] = viewport.project([
        selectedMarker.longitude,
        selectedMarker.latitude,
      ]);
      return { x, y };
    } catch {
      return null;
    }
  }, [selectedMarker, viewState, containerSize]);

  useEffect(() => {
    if (!mapData || mapData.length === 0) return;

    const signature = `${mapData.length}_${mapData[0]?.float_id}_${mapData[0]?.latitude}_${mapData[0]?.longitude}`;
    if (signature === prevDataSignatureRef.current) return;
    prevDataSignatureRef.current = signature;

    const lats = mapData
      .map((m) => m.latitude)
      .filter((n) => typeof n === "number" && !isNaN(n));
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
    if (mapData.length === 1 || maxSpan < 0.02) {
      zoom = 7.5;
    } else if (maxSpan < 0.1) {
      zoom = 10.0;
    } else if (maxSpan < 0.5) {
      zoom = 8.5;
    } else if (maxSpan < 2.0) {
      zoom = 7.0;
    } else if (maxSpan < 5.0) {
      zoom = 6.0;
    } else if (maxSpan < 12.0) {
      zoom = 5.0;
    } else if (maxSpan < 25.0) {
      zoom = 4.2;
    } else {
      zoom = 3.5;
    }

    setViewState({
      longitude: centerLon,
      latitude: centerLat,
      zoom,
      pitch: 0,
      bearing: 0,
    });
  }, [mapData]);

  const trajectoryPaths = useMemo(() => {
    if (!mapData || mapData.length === 0) return [];
    const grouped = mapData.reduce((acc, curr) => {
      if (!acc[curr.float_id]) {
        acc[curr.float_id] = {
          float_id: curr.float_id,
          path: [],
          status: curr.status,
        };
      }
      if (typeof curr.longitude === "number" && typeof curr.latitude === "number") {
        acc[curr.float_id].path.push([curr.longitude, curr.latitude]);
      }
      return acc;
    }, {} as Record<string, { float_id: string; path: [number, number][]; status?: string }>);

    return Object.values(grouped).filter((t) => t.path.length >= 2);
  }, [mapData]);

  const sortedMapData = useMemo(() => {
    if (!mapData || mapData.length === 0) return [];
    return [...mapData].sort((a, b) => {
      const aScore =
        a.float_id === selectedFloat || a.selected
          ? 2
          : a.float_id === hoveredFloat
            ? 1
            : 0;
      const bScore =
        b.float_id === selectedFloat || b.selected
          ? 2
          : b.float_id === hoveredFloat
            ? 1
            : 0;
      return aScore - bScore;
    });
  }, [mapData, selectedFloat, hoveredFloat]);

  const highlightedMarkers = useMemo(() => {
    if (!mapData || mapData.length === 0) return [];
    return mapData.filter(
      (d) =>
        d.float_id === selectedFloat || d.selected || d.float_id === hoveredFloat
    );
  }, [mapData, selectedFloat, hoveredFloat]);

  const layers = useMemo(() => {
    const list: any[] = [];

    if (radiusCenter && radiusKm) {
      list.push(
        new ScatterplotLayer({
          id: "radius-circle-layer",
          data: [radiusCenter],
          getPosition: (d: any) => [d.lon, d.lat],
          getRadius: radiusKm * 1000,
          radiusUnits: "meters",
          getFillColor: [2, 132, 199, 30],
          getLineColor: [2, 132, 199, 180],
          getLineWidth: 2,
          stroked: true,
          filled: true,
          pickable: false,
        })
      );
    }

    if (trajectoryPaths.length > 0) {
      list.push(
        new PathLayer({
          id: "float-trajectories-layer",
          data: trajectoryPaths,
          getPath: (d: any) => d.path,
          getColor: (d: any) => {
            if (d.status === "active") return [14, 165, 233, 230];
            if (d.status === "drifted") return [245, 158, 11, 230];
            if (d.status === "inactive") return [100, 116, 139, 230];
            return [14, 165, 233, 220];
          },
          getWidth: 3,
          widthMinPixels: 2.5,
          widthMaxPixels: 6,
          pickable: true,
          onClick: (info: any) => {
            if (info && info.object && info.object.float_id) {
              onSelectFloat(info.object.float_id);
            }
          },
        })
      );
    }

    if (highlightedMarkers.length > 0) {
      list.push(
        new ScatterplotLayer({
          id: "marker-selection-ring",
          data: highlightedMarkers,
          getPosition: (d: any) => [d.longitude, d.latitude],
          getRadius: (d: any) =>
            d.float_id === selectedFloat || d.selected ? 19 : 14,
          radiusUnits: "pixels",
          filled: false,
          stroked: true,
          getLineColor: (d: any) =>
            d.float_id === selectedFloat || d.selected
              ? [56, 189, 248, 255]
              : [14, 165, 233, 180],
          getLineWidth: (d: any) =>
            d.float_id === selectedFloat || d.selected ? 3.5 : 2,
          pickable: false,
        })
      );
    }

    if (sortedMapData.length > 0) {
      list.push(
        new ScatterplotLayer({
          id: "float-markers-layer",
          data: sortedMapData,
          getPosition: (d: any) => [d.longitude, d.latitude],
          getFillColor: (d: any) => {
            if (d.float_id === selectedFloat || d.selected)
              return [56, 189, 248, 255];
            if (d.status === "active") return [14, 165, 233, 245];
            if (d.status === "drifted") return [245, 158, 11, 245];
            if (d.status === "inactive") return [100, 116, 139, 230];
            return [14, 165, 233, 235];
          },
          getLineColor: (d: any) =>
            d.float_id === selectedFloat || d.selected
              ? [255, 255, 255, 255]
              : [255, 255, 255, 240],
          getRadius: (d: any) =>
            d.float_id === selectedFloat || d.selected
              ? 11
              : d.float_id === hoveredFloat
                ? 8.5
                : 6.5,
          radiusMinPixels: 6,
          radiusMaxPixels: 18,
          stroked: true,
          lineWidthMinPixels: 1.8,
          pickable: true,
          onClick: (info: any) => {
            if (info && info.object && info.object.float_id) {
              onSelectFloat(info.object.float_id);
            } else if (!info || !info.object) {
              onSelectFloat(null);
            }
          },
        })
      );
    }

    return list;
  }, [
    sortedMapData,
    highlightedMarkers,
    selectedFloat,
    hoveredFloat,
    radiusCenter,
    radiusKm,
    trajectoryPaths,
    onSelectFloat,
  ]);

  const getTooltip = useCallback(
    ({ object }: { object?: MapData }) => {
      if (!object || object.float_id === selectedFloat) return null;

      let dateDisplay = "N/A";
      if (
        object.profile_date &&
        object.profile_date !== "NaT" &&
        object.profile_date !== "Unknown"
      ) {
        try {
          const d = new Date(object.profile_date);
          if (!isNaN(d.getTime())) {
            dateDisplay = d.toLocaleDateString("en-GB", {
              day: "2-digit",
              month: "short",
              year: "numeric",
            });
          } else {
            dateDisplay = object.profile_date.slice(0, 10);
          }
        } catch {
          dateDisplay = object.profile_date.slice(0, 10);
        }
      }

      const profileDisplay =
        typeof object.profile_number === "number" && !isNaN(object.profile_number)
          ? `Profile #${object.profile_number}`
          : `Float ${object.float_id}`;

      return {
        html: `<div style="background: rgba(15, 23, 42, 0.96); backdrop-filter: blur(8px); border: 1px solid rgba(51, 65, 85, 0.85); padding: 8px 12px; border-radius: 10px; color: #f8fafc; font-size: 12px; font-family: Inter, system-ui, sans-serif; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.4); pointer-events: none; min-width: 140px;">
          <div style="font-weight: 700; color: #ffffff; font-size: 13px; margin-bottom: 3px;">${profileDisplay}</div>
          <div style="font-size: 11px; color: #cbd5e1; margin-bottom: 2px;">Status: <span style="font-weight: 700; text-transform: uppercase; color: ${object.status === "active"
            ? "#38bdf8"
            : object.status === "drifted"
              ? "#fbbf24"
              : "#94a3b8"
          }">${object.status || "unknown"}</span></div>
          <div style="font-size: 11px; color: #94a3b8;">Date: <span style="color: #e2e8f0; font-weight: 500;">${dateDisplay}</span></div>
        </div>`,
      };
    },
    [selectedFloat]
  );

  // Compute popup clamped position (keep card within container bounds)
  const clampedPopupPos = useMemo(() => {
    if (!popupPosition) return null;
    const cardW = 320;
    const cardH = 340;
    const x = Math.max(8, Math.min(popupPosition.x - cardW / 2, containerSize.width - cardW - 8));
    const y = Math.max(8, Math.min(popupPosition.y - cardH - 30, containerSize.height - cardH - 8));
    return { x, y };
  }, [popupPosition, containerSize]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.6 }}
      className="relative h-full bg-surface-950 border border-surface-800/60 rounded-2xl overflow-hidden shadow-lg"
      ref={containerRef}
    >
      {/* Panel Header */}
      <div className="absolute top-3 left-4 z-[400] flex items-center gap-2 px-3.5 py-2 bg-surface-900/92 backdrop-blur-md border border-surface-700/60 rounded-xl shadow-lg text-surface-100 pointer-events-none">
        <Globe className="w-4 h-4 text-ocean-400" />
        <span className="text-xs font-semibold text-surface-100 tracking-tight">
          India Region Dashboard
        </span>
        {markerCount > 0 && (
          <span className="ml-1.5 text-[11px] px-2 py-0.5 rounded-md bg-ocean-500/15 text-ocean-300 font-semibold border border-ocean-500/30">
            {markerCount} float{markerCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Selected float indicator */}
      {selectedFloat && (
        <div className="absolute top-16 left-4 z-[400] flex items-center gap-2 px-3 py-1.5 rounded-xl bg-ocean-950/90 border border-ocean-700/50 backdrop-blur-md shadow-lg text-ocean-200">
          <Crosshair className="w-3.5 h-3.5 text-ocean-400 animate-pulse" />
          <span className="text-xs font-semibold text-ocean-200 tracking-tight">
            Selected: Float {selectedFloat}
          </span>
          <button
            onClick={() => onSelectFloat(null)}
            className="ml-1 text-ocean-400 hover:text-ocean-200 text-xs font-bold px-1.5 py-0.5 rounded hover:bg-ocean-800/60 transition-colors cursor-pointer"
            title="Clear selection"
          >
            ✕
          </button>
        </div>
      )}

      {/* Map + DeckGL */}
      <div className="h-full w-full">
        <DeckGL
          viewState={viewState}
          onViewStateChange={(e: any) => setViewState(e.viewState)}
          controller={true}
          layers={layers}
          getTooltip={getTooltip}
          pickingRadius={12}
          onHover={({ object }: any) =>
            setHoveredFloat(object ? object.float_id : null)
          }
        >
          <Map mapStyle={MAP_STYLE}>
            <NavigationControl position="bottom-right" />
          </Map>
        </DeckGL>
      </div>

      {/* ─── POPUP CARD: Rendered OUTSIDE DeckGL to avoid canvas event interception ─── */}
      <AnimatePresence>
        {selectedMarker && clampedPopupPos && (
          <motion.div
            key={selectedMarker.float_id}
            initial={{ opacity: 0, scale: 0.92, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            style={{
              position: "absolute",
              left: clampedPopupPos.x,
              top: clampedPopupPos.y,
              zIndex: 9999,
            }}
            className="w-[310px] pointer-events-auto"
          >
            <div className="bg-surface-900/98 backdrop-blur-xl rounded-2xl shadow-[0_20px_60px_-10px_rgba(0,0,0,0.7)] border border-surface-700/50 p-4 text-surface-100 font-sans select-none overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between gap-2 pb-3 border-b border-surface-700/40">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-8 h-8 rounded-lg bg-ocean-500/15 border border-ocean-500/30 flex items-center justify-center">
                    <Globe className="w-4 h-4 text-ocean-400" />
                  </div>
                  <div className="min-w-0">
                    <span className="text-sm font-extrabold text-surface-50 tracking-tight block truncate">
                      Float {selectedMarker.float_id}
                    </span>
                    {selectedMarker.manufacturer && (
                      <span className="text-[10px] font-medium text-ocean-300/80 flex items-center gap-1">
                        <Factory className="w-3 h-3" />
                        {selectedMarker.manufacturer}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {selectedMarker.status && (
                    <span
                      className={`flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border capitalize shrink-0 ${
                        selectedMarker.status === "active"
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                          : selectedMarker.status === "drifted"
                            ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                            : "bg-surface-700/50 text-surface-400 border-surface-600/50"
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                          selectedMarker.status === "active"
                            ? "bg-emerald-400 animate-pulse"
                            : selectedMarker.status === "drifted"
                              ? "bg-amber-400"
                              : "bg-surface-500"
                        }`}
                      />
                      {selectedMarker.status}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => onSelectFloat(null)}
                    className="w-6 h-6 flex items-center justify-center rounded-lg text-surface-400 hover:text-surface-100 hover:bg-surface-700/60 transition-colors shrink-0 cursor-pointer"
                    title="Close"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Details Grid */}
              <div className="grid grid-cols-2 gap-x-3 gap-y-2 py-3 border-b border-surface-700/40 text-xs">
                <div>
                  <span className="text-surface-500 block font-medium text-[10px] uppercase tracking-wider">DAC</span>
                  <span className="font-bold text-surface-200 uppercase">{selectedMarker.dac || "N/A"}</span>
                </div>
                <div>
                  <span className="text-surface-500 block font-medium text-[10px] uppercase tracking-wider">Last Report</span>
                  <span className="font-bold text-surface-200">
                    {selectedMarker.profile_date
                      ? new Date(selectedMarker.profile_date).toLocaleDateString("en-GB", {
                          day: "2-digit", month: "short", year: "numeric",
                        })
                      : "Unknown"}
                  </span>
                </div>
                <div>
                  <span className="text-surface-500 block font-medium text-[10px] uppercase tracking-wider">Latitude</span>
                  <span className="font-bold text-surface-200">
                    {typeof selectedMarker.latitude === "number"
                      ? `${Math.abs(selectedMarker.latitude).toFixed(2)}° ${selectedMarker.latitude >= 0 ? "N" : "S"}`
                      : "N/A"}
                  </span>
                </div>
                <div>
                  <span className="text-surface-500 block font-medium text-[10px] uppercase tracking-wider">Longitude</span>
                  <span className="font-bold text-surface-200">
                    {typeof selectedMarker.longitude === "number"
                      ? `${Math.abs(selectedMarker.longitude).toFixed(2)}° ${selectedMarker.longitude >= 0 ? "E" : "W"}`
                      : "N/A"}
                  </span>
                </div>
              </div>

              {/* Sensors */}
              <div className="py-2.5 border-b border-surface-700/40">
                <div className="text-[10px] font-bold uppercase tracking-wider text-surface-500 mb-1.5">
                  Sensors ({selectedMarker.variables?.length || 3})
                </div>
                <div className="text-[11px] font-semibold text-surface-300 bg-surface-800/60 px-3 py-2 rounded-lg border border-surface-700/40 leading-relaxed text-center break-words">
                  {(() => {
                    const vars = selectedMarker.variables?.length
                      ? selectedMarker.variables
                      : ["TEMP", "PSAL", "PRES"];
                    if (vars.length <= 4 || showAllSensors) return vars.join(" • ");
                    return vars.slice(0, 4).join(" • ") + ` • +${vars.length - 4} more`;
                  })()}
                </div>
                {selectedMarker.variables && selectedMarker.variables.length > 4 && (
                  <button
                    type="button"
                    onClick={() => setShowAllSensors(!showAllSensors)}
                    className="w-full mt-1.5 py-1 text-center text-[10px] font-bold text-ocean-400 hover:text-ocean-300 hover:bg-ocean-500/10 rounded-lg transition-colors cursor-pointer"
                  >
                    {showAllSensors ? "Show fewer ▲" : `Show all (${selectedMarker.variables.length}) ▼`}
                  </button>
                )}
              </div>

              {/* Action Buttons */}
              {onDrillDown && (
                <div className="flex flex-col gap-2 pt-3">
                  <button
                    type="button"
                    onClick={() => {
                      onSelectFloat(null);
                      onDrillDown(`Sensors on float ${selectedMarker.float_id}`);
                    }}
                    className="w-full min-h-[40px] py-2 px-3 rounded-xl bg-surface-800 hover:bg-surface-700 active:bg-surface-600 text-surface-100 font-bold text-xs transition-all flex items-center justify-center gap-2 border border-surface-700/60 cursor-pointer"
                  >
                    🔍 View Metadata
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onSelectFloat(null);
                      onDrillDown(`Show trajectory of float ${selectedMarker.float_id}`);
                    }}
                    className="w-full min-h-[40px] py-2 px-3 rounded-xl bg-gradient-to-r from-ocean-600 to-ocean-500 hover:from-ocean-500 hover:to-ocean-400 active:from-ocean-700 active:to-ocean-600 text-white font-bold text-xs transition-all flex items-center justify-center gap-2 shadow-lg shadow-ocean-500/20 border border-ocean-500/30 cursor-pointer"
                  >
                    🛰 Show Trajectory
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
