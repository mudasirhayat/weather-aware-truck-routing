/** Scrollable checkpoint list for the selected route. */

import { useMemo, useState } from "react";

import { formatDayTime, formatMiles } from "../lib/format";
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS } from "../lib/risk";
import type { RiskLevel, Route } from "../types";

interface CheckpointTableProps {
  route: Route;
  onFocusCheckpoint: (index: number) => void;
}

export function CheckpointTable({ route, onFocusCheckpoint }: CheckpointTableProps) {
  const [minLevel, setMinLevel] = useState<RiskLevel | "all">("all");

  const rows = useMemo(() => {
    if (minLevel === "all") return route.checkpoints;
    const floor = RISK_LEVELS.indexOf(minLevel);
    return route.checkpoints.filter(
      (checkpoint) => (checkpoint.risk?.level_score ?? -1) >= floor,
    );
  }, [route.checkpoints, minLevel]);

  return (
    <section className="checkpoints">
      <header className="checkpoints__head">
        <h3>
          Checkpoints
          <span className="checkpoints__count">
            {rows.length} of {route.checkpoints.length} · every{" "}
            {route.checkpoint_interval_miles} mi
          </span>
        </h3>
        <label className="checkpoints__filter">
          <span>Show</span>
          <select
            value={minLevel}
            onChange={(event) => setMinLevel(event.target.value as RiskLevel | "all")}
          >
            <option value="all">All</option>
            {RISK_LEVELS.slice(1).map((level) => (
              <option key={level} value={level}>
                {RISK_LABEL[level]} and worse
              </option>
            ))}
          </select>
        </label>
      </header>

      {route.checkpoint_interval_coarsened && (
        <p className="checkpoints__note">
          This trip is long enough that the interval was widened to keep the
          forecast request reasonable.
        </p>
      )}

      <div className="checkpoints__scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Mile</th>
              <th scope="col">ETA</th>
              <th scope="col">Wind</th>
              <th scope="col">Rain</th>
              <th scope="col">Snow</th>
              <th scope="col">Risk</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((checkpoint) => (
              <tr
                key={checkpoint.index}
                onClick={() => onFocusCheckpoint(checkpoint.index)}
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onFocusCheckpoint(checkpoint.index);
                  }
                }}
              >
                <td>{formatMiles(checkpoint.distance_miles)}</td>
                <td>{formatDayTime(checkpoint.eta)}</td>
                <td>{checkpoint.weather ? `${checkpoint.weather.wind_mph.toFixed(0)} mph` : "—"}</td>
                <td>{checkpoint.weather ? checkpoint.weather.rain_in_hr.toFixed(2) : "—"}</td>
                <td>{checkpoint.weather ? checkpoint.weather.snow_in_hr.toFixed(2) : "—"}</td>
                <td>
                  {checkpoint.risk ? (
                    <span
                      className="pill pill--sm"
                      style={{ background: RISK_COLOR[checkpoint.risk.level] }}
                      title={checkpoint.risk.drivers.join(" · ")}
                    >
                      {RISK_LABEL[checkpoint.risk.level]}
                      {checkpoint.risk.escalated_by_load && " ⚑"}
                    </span>
                  ) : (
                    <span className="pill pill--sm pill--unknown">No data</span>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="checkpoints__empty">
                  No checkpoints at this risk level — the route is clear.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
