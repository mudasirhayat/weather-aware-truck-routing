/** Stacked bar showing how a route's miles split across risk levels. */

import { formatMiles } from "../lib/format";
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS } from "../lib/risk";
import type { RouteMetrics } from "../types";

export function RiskBar({ metrics }: { metrics: RouteMetrics }) {
  const segments = RISK_LEVELS.map((level) => ({
    level,
    miles: metrics.miles_by_level[level] ?? 0,
  })).filter((segment) => segment.miles > 0);

  const unknown = metrics.unknown_weather_miles;
  const total = segments.reduce((sum, segment) => sum + segment.miles, 0) + unknown;
  if (total <= 0) return null;

  return (
    <div
      className="risk-bar"
      role="img"
      aria-label={segments
        .map((segment) => `${RISK_LABEL[segment.level]} ${formatMiles(segment.miles)}`)
        .join(", ")}
    >
      {segments.map((segment) => (
        <span
          key={segment.level}
          className="risk-bar__segment"
          style={{
            width: `${(segment.miles / total) * 100}%`,
            background: RISK_COLOR[segment.level],
          }}
          title={`${RISK_LABEL[segment.level]}: ${formatMiles(segment.miles)}`}
        />
      ))}
      {unknown > 0 && (
        <span
          className="risk-bar__segment risk-bar__segment--unknown"
          style={{ width: `${(unknown / total) * 100}%` }}
          title={`No forecast: ${formatMiles(unknown)}`}
        />
      )}
    </div>
  );
}
