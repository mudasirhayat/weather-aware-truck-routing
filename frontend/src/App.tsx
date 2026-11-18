/** Weather-aware truck routing: form + map + route comparison. */

import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchRules } from "./api/client";
import { CheckpointTable } from "./components/CheckpointTable";
import { Legend } from "./components/Legend";
import { MapView } from "./components/MapView";
import { RouteCard } from "./components/RouteCard";
import { TimeSlider } from "./components/TimeSlider";
import { TripForm } from "./components/TripForm";
import { formatFull, formatPounds } from "./lib/format";
import { useHeatmap } from "./lib/useHeatmap";
import { useTripPlan } from "./lib/useTripPlan";
import type { RiskRules, TripFormValues } from "./types";

const HEATMAP_HOURS = 48;
const DEFAULT_INTERVALS = [10, 25, 50];

export default function App() {
  const { status, plan, error, submit } = useTripPlan();
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [showCheckpoints, setShowCheckpoints] = useState(true);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [focusCheckpoint, setFocusCheckpoint] = useState<{
    routeId: string;
    index: number;
  } | null>(null);
  const [rules, setRules] = useState<RiskRules | null>(null);

  // The thresholds come from the backend so the legend can't drift from the
  // engine. A failure here is cosmetic, so it degrades silently.
  useEffect(() => {
    const controller = new AbortController();
    fetchRules(controller.signal)
      .then(setRules)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  // A fresh plan selects its recommended route and rewinds the slider.
  useEffect(() => {
    if (!plan) return;
    setSelectedRouteId(plan.recommendation.route_id);
    setHour(0);
    setPlaying(false);
    setFocusCheckpoint(null);
  }, [plan]);

  const selectedRoute = useMemo(
    () => plan?.routes.find((route) => route.id === selectedRouteId) ?? plan?.routes[0] ?? null,
    [plan, selectedRouteId],
  );

  const { heatmap, loading: heatmapLoading, error: heatmapError } = useHeatmap(
    plan?.plan_id ?? null,
    selectedRoute?.id ?? null,
    HEATMAP_HOURS,
    showHeatmap,
  );

  // Changing routes can shorten the timeline; keep the hour in range.
  useEffect(() => {
    if (heatmap && hour > heatmap.hours) setHour(0);
  }, [heatmap, hour]);

  const handleSubmit = useCallback(
    (values: TripFormValues) => {
      setPlaying(false);
      submit(values);
    },
    [submit],
  );

  const orderedRoutes = useMemo(
    () => (plan ? [...plan.routes].sort((a, b) => a.rank - b.rank) : []),
    [plan],
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="sidebar__head">
          <h1>Weather-aware truck routing</h1>
          <p>
            Three routes, scored against wind, rain and snow at the truck&apos;s
            predicted arrival time at every checkpoint.
          </p>
        </header>

        <TripForm
          onSubmit={handleSubmit}
          loading={status === "loading"}
          intervalOptions={rules?.interval_options_miles ?? DEFAULT_INTERVALS}
        />

        {status === "error" && error && (
          <p className="alert alert--error" role="alert">
            {error}
          </p>
        )}

        {plan && (
          <section className="summary">
            <h2>Recommendation</h2>
            <p className="summary__reason">{plan.recommendation.reason}</p>
            {!plan.recommendation.travel_advised && (
              <p className="alert alert--warning">
                Every option crosses conditions rated <strong>No travel</strong> for
                a {formatPounds(plan.request.load_lb)} load. Consider delaying
                departure.
              </p>
            )}
            <ol className="summary__criteria">
              {plan.recommendation.criteria.map((criterion) => (
                <li key={criterion}>{criterion}</li>
              ))}
            </ol>
          </section>
        )}

        {orderedRoutes.length > 0 && (
          <section className="routes">
            <h2>Route options</h2>
            {orderedRoutes.map((route) => (
              <RouteCard
                key={route.id}
                route={route}
                selected={route.id === selectedRoute?.id}
                onSelect={() => setSelectedRouteId(route.id)}
              />
            ))}
          </section>
        )}

        <Legend rules={rules} />

        {plan && (
          <footer className="sidebar__foot">
            <p>
              {plan.meta.weather_points_fetched} forecast points for{" "}
              {plan.meta.weather_points_requested} checkpoints
              {plan.meta.elapsed_ms ? ` · planned in ${(plan.meta.elapsed_ms / 1000).toFixed(1)}s` : ""}
            </p>
            <p>
              {Object.entries(plan.meta.providers)
                .map(([key, value]) => `${key}: ${value}`)
                .join(" · ")}
            </p>
          </footer>
        )}
      </aside>

      <main className="stage">
        <div className="stage__map">
          {plan ? (
            <MapView
              routes={plan.routes}
              selectedRouteId={selectedRoute?.id ?? null}
              onSelectRoute={setSelectedRouteId}
              heatmap={heatmap}
              heatmapHour={hour}
              showHeatmap={showHeatmap}
              showCheckpoints={showCheckpoints}
              focusCheckpoint={focusCheckpoint}
            />
          ) : (
            <div className="stage__placeholder">
              {status === "loading" ? (
                <>
                  <div className="spinner" aria-hidden />
                  <p>Fetching routes and forecasts…</p>
                </>
              ) : (
                <>
                  <h2>Plan a trip to begin</h2>
                  <p>
                    Enter an origin, destination, departure time and load weight.
                    We&apos;ll generate three routes, sample the weather at every
                    checkpoint, and recommend the safest one.
                  </p>
                </>
              )}
            </div>
          )}

          {plan && (
            <div className="map-controls">
              <label>
                <input
                  type="checkbox"
                  checked={showHeatmap}
                  onChange={(event) => {
                    setShowHeatmap(event.target.checked);
                    if (!event.target.checked) setPlaying(false);
                  }}
                />
                Heatmap
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={showCheckpoints}
                  onChange={(event) => setShowCheckpoints(event.target.checked)}
                />
                Checkpoints
              </label>
            </div>
          )}
        </div>

        {plan && (
          <div className="stage__panel">
            <div className="stage__slider">
              {showHeatmap ? (
                <>
                  <TimeSlider
                    timeline={heatmap?.timeline ?? []}
                    hour={hour}
                    onChange={setHour}
                    playing={playing}
                    onTogglePlay={() => setPlaying((value) => !value)}
                    disabled={!heatmap || heatmapLoading}
                  />
                  <p className="stage__slider-note">
                    {heatmapLoading && "Loading corridor forecast…"}
                    {heatmapError && <span className="is-error">{heatmapError}</span>}
                    {heatmap && !heatmapLoading && !heatmapError && (
                      <>
                        {heatmap.meta.point_count} corridor samples ·{" "}
                        {heatmap.route_label} · departure {formatFull(heatmap.anchor)}
                      </>
                    )}
                  </p>
                </>
              ) : (
                <p className="stage__slider-note">
                  Enable the heatmap to scrub the 0–{HEATMAP_HOURS} hour forecast.
                </p>
              )}
            </div>

            {selectedRoute && (
              <CheckpointTable
                route={selectedRoute}
                onFocusCheckpoint={(index) =>
                  setFocusCheckpoint({ routeId: selectedRoute.id, index })
                }
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}
