"use client";

import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { FarmProps, FeatureCollection } from "@/types/api";

// MapLibre 6 runs its web worker from a separate module served from /public (copied on npm install).
maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const COLORS = { no_indications: "#2e6b3f", risk_identified: "#a3332a", insufficient_information: "#9a6a0b", none: "#5b6770" };

// Public OpenStreetMap raster tiles. If the browser is offline the farm layers still render on a plain background.
const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#efeadf" } },
    { id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.6, "raster-opacity": 0.85 } },
  ],
};

const resultExpr: ExpressionSpecification = [
  "match",
  ["coalesce", ["get", "result"], "none"],
  "no_indications",
  COLORS.no_indications,
  "risk_identified",
  COLORS.risk_identified,
  "insufficient_information",
  COLORS.insufficient_information,
  COLORS.none,
];

function flatten(fc: FeatureCollection<FarmProps>): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const f of fc.features) {
    if (!f.geometry) continue;
    const { assessment, ...rest } = f.properties;
    features.push({ type: "Feature", geometry: f.geometry, properties: { ...rest, result: assessment?.result ?? "none" } });
  }
  return { type: "FeatureCollection", features };
}

export default function FarmMap({
  farms,
  layers,
  onSelect,
}: {
  farms: FeatureCollection<FarmProps>;
  layers: GeoJSON.FeatureCollection;
  onSelect: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!ref.current || map.current) return;
    const m = new maplibregl.Map({ container: ref.current, style: STYLE, center: [-76.05, 1.86], zoom: 11.5 });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("layers", { type: "geojson", data: layers });
      m.addLayer({ id: "forest", type: "fill", source: "layers", filter: ["==", ["get", "layer"], "forest_2020"], paint: { "fill-color": "#3f7a4f", "fill-opacity": 0.25 } });
      m.addLayer({ id: "loss", type: "fill", source: "layers", filter: ["==", ["get", "layer"], "forest_loss_after_2020"], paint: { "fill-color": "#a3332a", "fill-opacity": 0.45 } });
      m.addSource("farms", { type: "geojson", data: flatten(farms) });
      m.addLayer({ id: "plots", type: "line", source: "farms", filter: ["==", ["get", "geometry_kind"], "polygon"], paint: { "line-color": resultExpr, "line-width": 2.5 } });
      m.addLayer({
        id: "points",
        type: "circle",
        source: "farms",
        filter: ["==", ["get", "geometry_kind"], "point"],
        paint: { "circle-radius": 7, "circle-color": resultExpr, "circle-stroke-color": "#fcfbf8", "circle-stroke-width": 2 },
      });
      const bounds = new maplibregl.LngLatBounds();
      flatten(farms).features.forEach((f) => {
        const g = f.geometry;
        if (g.type === "Point") bounds.extend(g.coordinates as [number, number]);
        if (g.type === "Polygon") g.coordinates[0].forEach((c) => bounds.extend(c as [number, number]));
      });
      if (!bounds.isEmpty()) m.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 0 });
      for (const id of ["points", "plots"]) {
        m.on("click", id, (e: MapLayerMouseEvent) => {
          const f = e.features?.[0];
          if (!f) return;
          const p = f.properties as Record<string, string>;
          onSelect(p.id);
          new maplibregl.Popup({ closeButton: false })
            .setLngLat(e.lngLat)
            .setHTML(`<strong>${p.name}</strong><br/>${p.producer}<br/>${p.vereda ?? ""} ${p.municipality ?? ""}`)
            .addTo(m);
        });
        m.on("mouseenter", id, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", id, () => (m.getCanvas().style.cursor = ""));
      }
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // The map is created once; data updates are applied in the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const src = map.current?.getSource("farms") as GeoJSONSource | undefined;
    src?.setData(flatten(farms));
  }, [farms]);

  return <div ref={ref} className="h-[520px] w-full rounded-sm border border-line" />;
}
