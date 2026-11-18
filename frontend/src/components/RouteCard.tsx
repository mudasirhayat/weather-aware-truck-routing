/** One route option: ranking, headline numbers, and its risk breakdown. */

import { formatDayTime, formatDuration, formatMiles } from "../lib/format";
import { RISK_COLOR, RISK_LABEL } from "../lib/risk";
import type { Route } from "../types";
import { RiskBar } from "./RiskBar";

interface RouteCardProps {
  route: Route;
  selected: boolean;
  onSelect: () => void;
}

export function RouteCard({ route, selected, onSelect }: RouteCardProps) {
  const { metrics } = route;
  const severe = metrics.miles_by_level.severe;
  const high = metrics.miles_by_level.high;
  const blocked = metrics.miles_by_level.no_travel;

  return (
    <article
      className={[
        "route-card",
        selected ? "is-selected" : "",
        route.recommended ? "is-recommended" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button className="route-card__hit" type="button" onClick={onSelect} aria-pressed={selected}>
        <header className="route-card__head">
          <span className="route-card__rank">#{route.rank}</span>
          <h3>{route.label}</h3>
          {route.recommended && <span className="badge badge--rec">Recommended</span>}
        </header>

        <dl className="route-card__stats">
          <div>
            <dt>Distance</dt>
            <dd>{formatMiles(metrics.distance_miles)}</dd>
          </div>
          <div>
            <dt>Drive time</dt>
            <dd>{formatDuration(metrics.duration_hours)}</dd>
          </div>
          <div>
            <dt>Arrival</dt>
            <dd>{formatDayTime(route.arrival)}</dd>
          </div>
          <div>
            <dt>Worst</dt>
            <dd>
              <span
                className="pill"
                style={{ background: RISK_COLOR[metrics.worst_level] }}
              >
                {RISK_LABEL[metrics.worst_level]}
              </span>
            </dd>
          </div>
        </dl>

        <RiskBar metrics={metrics} />

        <ul className="route-card__facts">
          {blocked > 0 && (
            <li className="is-critical">{formatMiles(blocked)} no-travel</li>
          )}
          <li>{formatMiles(severe)} severe</li>
          <li>{formatMiles(high)} high</li>
          <li>avg risk {metrics.average_risk.toFixed(2)}</li>
        </ul>

        {!metrics.travel_advised && (
          <p className="route-card__warning">
            Contains stretches the load cannot legally or safely cross.
          </p>
        )}
      </button>
    </article>
  );
}
