/** The map: three routes, risk-coloured checkpoints, and the corridor heatmap. */

import { useEffect, useMemo } from "react";
import {
  CircleMarker,
  MapContainer,
  Pane,
  Polyline,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";

import { colorRouteByRisk } from "../lib/polyline";
import { formatDayTime, formatMiles } from "../lib/format";
import { RISK_COLOR, RISK_LABEL } from "../lib/risk";
import type { Heatmap, Route, RiskLevel } from "../types";
import { HeatLayer } from "./HeatLayer";

interface MapViewProps {
  routes: Route[];
  selectedRouteId: string | null;
  onSelectRoute: (routeId: string) => void;
  heatmap: Heatmap | null;
  heatmapHour: number;
  showHeatmap: boolean;
  showCheckpoints: boolean;
  focusCheckpoint: { routeId: string; index: number } | null;
}

const FALLBACK_CENTER: L.LatLngTuple = [39.5, -98.35];

/** Pans/zooms to the selected route whenever it changes. */
function FitToRoute({ route }: { route: Route | null }) {
  const map = useMap();

  useEffect(() => {
    if (!route) return;
    const bounds = L.latLngBounds(route.bounds[0], route.bounds[1]);
    if (!bounds.isValid()) return;
    map.fitBounds(bounds, { padding: [48, 48], animate: true });
  }, [map, route]);

  return null;
}

/** Centres on a checkpoint when one is picked from the table. */
function FocusCheckpoint({
  focus,
  routes,
}: {
  focus: MapViewProps["focusCheckpoint"];
  routes: Route[];
}) {
  const map = useMap();

  useEffect(() => {
    if (!focus) return;
    const route = routes.find((candidate) => candidate.id === focus.routeId);
    const checkpoint = route?.checkpoints[focus.index];
    if (!checkpoint) return;
    map.flyTo([checkpoint.lat, checkpoint.lon], Math.max(map.getZoom(), 8), {
      duration: 0.6,
    });
  }, [map, focus, routes]);

  return null;
}

function CheckpointPopup({ route, index }: { route: Route; index: number }) {
  const checkpoint = route.checkpoints[index];
  const { weather, risk } = checkpoint;

  return (
    <div className="popup">
      <header>
        <strong>{formatMiles(checkpoint.distance_miles)}</strong>
        <span>{route.label}</span>
      </header>
      <p className="popup__eta">ETA {formatDayTime(checkpoint.eta)}</p>
      {risk ? (
        <>
          <p className="popup__level" style={{ background: RISK_COLOR[risk.level] }}>
            {RISK_LABEL[risk.level]}
            {risk.escalated_by_load ? " · load rule" : ""}
          </p>
          {weather && (
            <dl className="popup__grid">
              <dt>Wind</dt>
              <dd>
                {weather.wind_mph.toFixed(0)} mph
                <span className="popup__gust"> (gust {weather.gust_mph.toFixed(0)})</span>
              </dd>
              <dt>Rain</dt>
              <dd>{weather.rain_in_hr.toFixed(2)} in/hr</dd>
              <dt>Snow</dt>
              <dd>{weather.snow_in_hr.toFixed(2)} in/hr</dd>
              {weather.temperature_c !== null && (
                <>
                  <dt>Temp</dt>
                  <dd>{weather.temperature_c.toFixed(0)}&deg;C</dd>
                </>
              )}
            </dl>
          )}
          {risk.drivers.length > 0 && (
            <p className="popup__drivers">{risk.drivers.join(" · ")}</p>
          )}
        </>
      ) : (
        <p className="popup__level popup__level--unknown">
          {checkpoint.note ?? "No forecast for this time."}
        </p>
      )}
    </div>
  );
}

export function MapView({
  routes,
  selectedRouteId,
  onSelectRoute,
  heatmap,
  heatmapHour,
  showHeatmap,
  showCheckpoints,
  focusCheckpoint,
}: MapViewProps) {
  const selected = routes.find((route) => route.id === selectedRouteId) ?? routes[0] ?? null;

  // Risk colouring is the expensive bit, so it is cached per route.
  const colored = useMemo(
    () => (selected ? colorRouteByRisk(selected.geometry, selected.checkpoints) : []),
    [selected],
  );

  return (
    <MapContainer
      className="map"
      center={FALLBACK_CENTER}
      zoom={4}
      minZoom={3}
      // Canvas rendering keeps hundreds of checkpoint markers smooth; the DOM
      // renderer creates an element per marker and stutters while panning.
      preferCanvas
      worldCopyJump
    >
      {/* Standard OSM tiles: no API key, no sign-up, and the usage policy
          allows a project at this scale. */}
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
      />

      {showHeatmap && heatmap && (
        <HeatLayer points={heatmap.points} hourIndex={heatmapHour} />
      )}

      {/* Unselected routes sit under the chosen one. */}
      {routes
        .filter((route) => route.id !== selected?.id)
        .map((route) => (
          <Polyline
            key={route.id}
            positions={route.geometry}
            pathOptions={{
              color: "#475569",
              weight: 4,
              opacity: 0.45,
              dashArray: "1 7",
              lineCap: "round",
            }}
            eventHandlers={{ click: () => onSelectRoute(route.id) }}
          />
        ))}

      {selected && (
        <Pane name="selected-route" style={{ zIndex: 450 }}>
          {/* A dark casing under the coloured segments keeps thin risk bands
              legible against busy map tiles. */}
          <Polyline
            positions={selected.geometry}
            pathOptions={{ color: "#0f172a", weight: 11, opacity: 0.55, lineCap: "round" }}
          />
          {colored.map((segment) => (
            <Polyline
              key={segment.key}
              positions={segment.positions}
              pathOptions={{
                color: RISK_COLOR[segment.level as RiskLevel] ?? "#94a3b8",
                weight: 6,
                opacity: 1,
                lineCap: "butt",
              }}
            />
          ))}
        </Pane>
      )}

      {showCheckpoints && selected && (
        <Pane name="checkpoints" style={{ zIndex: 460 }}>
          {selected.checkpoints.map((checkpoint) => (
            <CircleMarker
              key={checkpoint.index}
              center={[checkpoint.lat, checkpoint.lon]}
              radius={checkpoint.index === 0 || checkpoint.index === selected.checkpoints.length - 1 ? 7 : 5}
              pathOptions={{
                color: "#ffffff",
                weight: 1.5,
                fillColor: checkpoint.risk ? RISK_COLOR[checkpoint.risk.level] : "#94a3b8",
                fillOpacity: 1,
              }}
            >
              <Popup>
                <CheckpointPopup route={selected} index={checkpoint.index} />
              </Popup>
            </CircleMarker>
          ))}
        </Pane>
      )}

      <FitToRoute route={selected} />
      <FocusCheckpoint focus={focusCheckpoint} routes={routes} />
    </MapContainer>
  );
}
