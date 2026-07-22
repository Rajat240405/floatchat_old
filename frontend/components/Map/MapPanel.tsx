"use client";

import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import Map, { NavigationControl, Source, Layer, Popup } from "react-map-gl/maplibre";
import { motion, AnimatePresence } from "framer-motion";
import { Globe, Crosshair, X, Factory } from "lucide-react";
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

const MAP_STYLE: any = {
  version: 8,
  sources: {
    esriOcean: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"
      ],
      tileSize: 256,
      attribution: "© Esri, GEBCO, NOAA, National Geographic"
    }
  },
  layers: [
    {
      id: "esri-ocean-raster",
      type: "raster",
      source: "esriOcean"
    }
  ]
};

/** Build a GeoJSON circle polygon approximating a radius in km */
function buildRadiusGeoJSON(lat: number, lon: number, radiusKm: number) {
  const points = 64;
  const earthR = 6371;
  const coords: [number, number][] = [];
  for (let i = 0; i <= points; i++) {
    const angle = (i / points) * 2 * Math.PI;
    const dLat = (radiusKm / earthR) * (180 / Math.PI) * Math.cos(angle);
    const dLon = (radiusKm / earthR) * (180 / Math.PI) * Math.sin(angle) / Math.cos((lat * Math.PI) / 180);
    coords.push([lon + dLon, lat + dLat]);
  }
  return {
    type: "FeatureCollection" as const,
    features: [{
      type: "Feature" as const,
      geometry: { type: "Polygon" as const, coordinates: [coords] },
      properties: {}
    }]
  };
}

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
    latitude: 12.0,
    zoom: 3.8,
  });
  const mapRef = useRef<any>(null);
  const prevDataSignatureRef = useRef<string>("");

  useEffect(() => {
    if (!selectedFloat) setShowAllSensors(false);
  }, [selectedFloat]);

  // Auto-zoom to fit markers when data changes
  useEffect(() => {
    if (!mapData || mapData.length === 0) return;

    const signature = `${mapData.length}_${mapData[0]?.float_id}_${mapData[0]?.latitude}_${mapData[0]?.longitude}`;
    if (signature === prevDataSignatureRef.current) return;
    prevDataSignatureRef.current = signature;

    const lats = mapData.map((m) => m.latitude).filter((n) => typeof n === "number" && !isNaN(n));
    const lons = mapData.map((m) => m.longitude).filter((n) => typeof n === "number" && !isNaN(n));
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
    if (mapData.length === 1 || maxSpan < 0.02) zoom = 7.5;
    else if (maxSpan < 0.1) zoom = 10.0;
    else if (maxSpan < 0.5) zoom = 8.5;
    else if (maxSpan < 2.0) zoom = 7.0;
    else if (maxSpan < 5.0) zoom = 6.0;
    else if (maxSpan < 12.0) zoom = 5.0;
    else if (maxSpan < 25.0) zoom = 4.2;
    else zoom = 3.5;

    setViewState({ longitude: centerLon, latitude: centerLat, zoom });
  }, [mapData]);

  const selectedMarker = useMemo(() => {
    if (!selectedFloat || !mapData) return null;
    return [...mapData].reverse().find((m) => m.float_id === selectedFloat) || null;
  }, [selectedFloat, mapData]);

  // ── GeoJSON: float markers ─────────────────────────────────────────────
  const markersGeoJSON = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: mapData.map((d) => ({
      type: "Feature" as const,
      geometry: {
        type: "Point" as const,
        coordinates: [d.longitude, d.latitude],
      },
      properties: {
        float_id: d.float_id,
        status: d.status || "unknown",
        dac: d.dac || "",
        profile_date: d.profile_date || "",
        selected: d.float_id === selectedFloat || !!d.selected,
        hovered: d.float_id === hoveredFloat,
        dimmed: !!selectedFloat && d.float_id !== selectedFloat && !d.selected,
      },
    })),
  }), [mapData, selectedFloat, hoveredFloat]);

  // ── GeoJSON: trajectory paths ──────────────────────────────────────────
  const trajectoryGeoJSON = useMemo(() => {
    const grouped: Record<string, { path: [number, number][]; status?: string }> = {};
    for (const d of mapData) {
      if (!grouped[d.float_id]) grouped[d.float_id] = { path: [], status: d.status };
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
  }, [mapData]);

  // ── GeoJSON: radius circle ─────────────────────────────────────────────
  const radiusGeoJSON = useMemo(() => {
    if (!radiusCenter || !radiusKm) return null;
    return buildRadiusGeoJSON(radiusCenter.lat, radiusCenter.lon, radiusKm);
  }, [radiusCenter, radiusKm]);

  // ── Layer definitions (stable references via useMemo) ──────────────────
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
        "match", ["get", "status"],
        "active",   "#00d2ff",
        "drifted",  "#ffa01e",
        "inactive", "#ff5050",
        "#00d2ff",
      ] as any,
      "line-width": 2.5,
      "line-opacity": 0.85,
    },
  };

  // Circle outline (halo) for selected float
  const markerHaloLayer = {
    id: "marker-halo",
    type: "circle" as const,
    filter: ["==", ["get", "selected"], true] as any,
    paint: {
      "circle-radius": 18,
      "circle-color": "transparent",
      "circle-stroke-width": 3,
      "circle-stroke-color": "#38bdf8",
    },
  };

  const markerLayer = {
    id: "float-markers",
    type: "circle" as const,
    paint: {
      "circle-radius": [
        "case",
        ["==", ["get", "selected"], true], 12,
        ["==", ["get", "hovered"],  true],  9,
        7,
      ] as any,
      "circle-color": [
        "case",
        ["==", ["get", "selected"], true], "#06b6d4",
        ["==", ["get", "dimmed"],   true],
          ["match", ["get", "status"],
            "active",   "rgba(99,202,255,0.5)",
            "rgba(255,165,60,0.4)"
          ],
        ["match", ["get", "status"],
          "active",   "#00d2ff",
          "drifted",  "#ffa01e",
          "inactive", "#ff5050",
          "#00d2ff",
        ],
      ] as any,
      "circle-stroke-width": [
        "case", ["==", ["get", "selected"], true], 2.5, 1.5
      ] as any,
      "circle-stroke-color": "#ffffff",
    },
  };

  // ── Interactivity ──────────────────────────────────────────────────────
  const onMapClick = useCallback((e: any) => {
    const features = e.features ?? [];
    const f = features.find((ft: any) => ft.layer?.id === "float-markers");
    if (f) {
      const fid = f.properties?.float_id;
      onSelectFloat(fid === selectedFloat ? null : fid);
    } else {
      onSelectFloat(null);
    }
  }, [selectedFloat, onSelectFloat]);

  const onMouseMove = useCallback((e: any) => {
    const features = e.features ?? [];
    const f = features.find((ft: any) => ft.layer?.id === "float-markers");
    setHoveredFloat(f ? f.properties?.float_id : null);
    if (mapRef.current) {
      mapRef.current.getCanvas().style.cursor = f ? "pointer" : "";
    }
  }, []);

  const onMouseLeave = useCallback(() => {
    setHoveredFloat(null);
    if (mapRef.current) {
      mapRef.current.getCanvas().style.cursor = "";
    }
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.6 }}
      className="relative h-full bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden shadow-lg"
    >
      {/* Panel Header */}
      <div className="absolute top-3 left-4 z-[400] flex items-center gap-2 px-3.5 py-2 bg-slate-900/90 backdrop-blur-md border border-slate-700/60 rounded-xl shadow-lg pointer-events-none">
        <Globe className="w-4 h-4 text-ocean-400" />
        <span className="text-xs font-semibold text-slate-100 tracking-tight">India Region Dashboard</span>
        {markerCount > 0 && (
          <span className="ml-1.5 text-[11px] px-2 py-0.5 rounded-md bg-ocean-500/15 text-ocean-300 font-semibold border border-ocean-500/30">
            {markerCount} float{markerCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Selected float indicator */}
      {selectedFloat && (
        <div className="absolute top-16 left-4 z-[400] flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-ocean-700/50 backdrop-blur-md shadow-lg text-ocean-200">
          <Crosshair className="w-3.5 h-3.5 text-ocean-400 animate-pulse" />
          <span className="text-xs font-semibold text-ocean-200 tracking-tight">
            Selected: Float {selectedFloat}
          </span>
          <button
            onClick={() => onSelectFloat(null)}
            className="ml-1 text-ocean-400 hover:text-ocean-200 text-xs font-bold px-1.5 py-0.5 rounded hover:bg-ocean-800/60 transition-colors cursor-pointer"
            title="Clear selection"
          >✕</button>
        </div>
      )}

      {/* MapLibre Map — all layers are geo-anchored */}
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

        {/* Radius circle */}
        {radiusGeoJSON && (
          <Source id="radius" type="geojson" data={radiusGeoJSON}>
            <Layer {...radiusFillLayer} />
            <Layer {...radiusLineLayer} />
          </Source>
        )}

        {/* Trajectory paths */}
        {trajectoryGeoJSON.features.length > 0 && (
          <Source id="trajectories" type="geojson" data={trajectoryGeoJSON}>
            <Layer {...trajectoryLayer} />
          </Source>
        )}

        {/* Float markers */}
        {markersGeoJSON.features.length > 0 && (
          <Source id="float-markers" type="geojson" data={markersGeoJSON}>
            <Layer {...markerHaloLayer} />
            <Layer {...markerLayer} />
          </Source>
        )}

        {/* Hover tooltip popup */}
        {hoveredFloat && !selectedFloat && (() => {
          const d = mapData.find((m) => m.float_id === hoveredFloat);
          if (!d) return null;
          return (
            <Popup
              longitude={d.longitude}
              latitude={d.latitude}
              closeButton={false}
              closeOnClick={false}
              anchor="bottom"
              offset={14}
            >
              <div className="text-xs font-sans p-1">
                <div className="font-bold text-slate-800">Float {d.float_id}</div>
                {d.dac && <div className="text-slate-500">DAC: {d.dac}</div>}
                <div className={`font-semibold capitalize ${
                  d.status === "active" ? "text-emerald-600" :
                  d.status === "drifted" ? "text-amber-600" : "text-red-500"
                }`}>{d.status || "unknown"}</div>
              </div>
            </Popup>
          );
        })()}
      </Map>

      {/* Selected float popup card — rendered as HTML overlay */}
      <AnimatePresence>
        {selectedMarker && (
          <motion.div
            key={selectedMarker.float_id}
            initial={{ opacity: 0, scale: 0.92, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="absolute bottom-12 left-4 z-[900] w-[300px] pointer-events-auto"
          >
            <div className="bg-slate-900/98 backdrop-blur-xl rounded-2xl shadow-2xl border border-slate-700/50 p-4 text-slate-100 font-sans select-none overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-700/40">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-8 h-8 rounded-lg bg-ocean-500/15 border border-ocean-500/30 flex items-center justify-center">
                    <Globe className="w-4 h-4 text-ocean-400" />
                  </div>
                  <div className="min-w-0">
                    <span className="text-sm font-extrabold text-slate-50 tracking-tight block truncate">
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
                    <span className={`flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border capitalize shrink-0 ${
                      selectedMarker.status === "active"
                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                        : selectedMarker.status === "drifted"
                          ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                          : "bg-slate-700/50 text-slate-400 border-slate-600/50"
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        selectedMarker.status === "active" ? "bg-emerald-400 animate-pulse" :
                        selectedMarker.status === "drifted" ? "bg-amber-400" : "bg-slate-500"
                      }`} />
                      {selectedMarker.status}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => onSelectFloat(null)}
                    className="w-6 h-6 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-700/60 transition-colors shrink-0 cursor-pointer"
                    title="Close"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Details Grid */}
              <div className="grid grid-cols-2 gap-x-3 gap-y-2 py-3 border-b border-slate-700/40 text-xs">
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">DAC</span>
                  <span className="font-bold text-slate-200 uppercase">{selectedMarker.dac || "N/A"}</span>
                </div>
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">Last Report</span>
                  <span className="font-bold text-slate-200">
                    {selectedMarker.profile_date
                      ? new Date(selectedMarker.profile_date).toLocaleDateString("en-GB", {
                          day: "2-digit", month: "short", year: "numeric",
                        })
                      : "Unknown"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">Latitude</span>
                  <span className="font-bold text-slate-200">
                    {typeof selectedMarker.latitude === "number"
                      ? `${Math.abs(selectedMarker.latitude).toFixed(2)}° ${selectedMarker.latitude >= 0 ? "N" : "S"}`
                      : "N/A"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block font-medium text-[10px] uppercase tracking-wider">Longitude</span>
                  <span className="font-bold text-slate-200">
                    {typeof selectedMarker.longitude === "number"
                      ? `${Math.abs(selectedMarker.longitude).toFixed(2)}° ${selectedMarker.longitude >= 0 ? "E" : "W"}`
                      : "N/A"}
                  </span>
                </div>
              </div>

              {/* Sensors */}
              <div className="py-2.5 border-b border-slate-700/40">
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                  Sensors ({selectedMarker.variables?.length || 3})
                </div>
                <div className="text-[11px] font-semibold text-slate-300 bg-slate-800/60 px-3 py-2 rounded-lg border border-slate-700/40 leading-relaxed text-center break-words">
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
                    className="w-full min-h-[38px] py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-100 font-bold text-xs transition-all flex items-center justify-center gap-2 border border-slate-700/60 cursor-pointer"
                  >
                    🔍 View Metadata
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onSelectFloat(null);
                      onDrillDown(`Show trajectory of float ${selectedMarker.float_id}`);
                    }}
                    className="w-full min-h-[38px] py-2 px-3 rounded-xl bg-gradient-to-r from-ocean-600 to-ocean-500 hover:from-ocean-500 hover:to-ocean-400 text-white font-bold text-xs transition-all flex items-center justify-center gap-2 shadow-lg shadow-ocean-500/20 border border-ocean-500/30 cursor-pointer"
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
