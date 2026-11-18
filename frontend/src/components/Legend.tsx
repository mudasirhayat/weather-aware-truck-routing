/** Risk colour key plus the thresholds the backend is actually enforcing. */

import { useState } from "react";

import { RISK_COLOR, RISK_LABEL, RISK_LEVELS } from "../lib/risk";
import type { RiskLevel, RiskRules } from "../types";

/**
 * Turn the API's band bounds back into the brief's printed ranges.
 *
 * Wind arrives as inclusive lower bounds, so a level's range runs up to the
 * next level's bound. Rain and snow arrive as inclusive upper bounds, so a
 * level's range starts just above the previous one.
 */
function windRange(rules: RiskRules, level: RiskLevel): string {
  const bounds = rules.wind_mph_lower_bounds;
  const index = bounds.findIndex((row) => row.level === level);
  if (index < 0) return "—";
  const from = bounds[index].at_or_above;
  const next = bounds[index + 1];
  if (index === 0) return `< ${next?.at_or_above ?? from} mph`;
  if (!next) return `≥ ${from} mph`;
  return `${from}–${next.at_or_above - 1} mph`;
}

function rateRange(
  bounds: { level: RiskLevel; up_to: number }[],
  level: RiskLevel,
  unit: string,
): string {
  const index = bounds.findIndex((row) => row.level === level);
  if (index < 0) {
    const top = bounds[bounds.length - 1];
    return top ? `> ${top.up_to.toFixed(2)} ${unit}` : "—";
  }
  const upper = bounds[index].up_to;
  if (index === 0) return `< ${upper.toFixed(2)} ${unit}`;
  return `${bounds[index - 1].up_to.toFixed(2)}–${upper.toFixed(2)} ${unit}`;
}

export function Legend({ rules }: { rules: RiskRules | null }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="legend">
      <ul className="legend__swatches">
        {RISK_LEVELS.map((level) => (
          <li key={level}>
            <span className="legend__dot" style={{ background: RISK_COLOR[level] }} />
            {RISK_LABEL[level]}
          </li>
        ))}
      </ul>

      {rules && (
        <>
          <button className="link" type="button" onClick={() => setOpen((value) => !value)}>
            {open ? "Hide thresholds" : "Show thresholds"}
          </button>
          {open && (
            <div className="legend__rules">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Level</th>
                    <th scope="col">Wind</th>
                    <th scope="col">Rain</th>
                    <th scope="col">Snow</th>
                  </tr>
                </thead>
                <tbody>
                  {RISK_LEVELS.map((level) => (
                    <tr key={level}>
                      <th scope="row">
                        <span className="legend__dot" style={{ background: RISK_COLOR[level] }} />
                        {RISK_LABEL[level]}
                      </th>
                      <td>{windRange(rules, level)}</td>
                      <td>{rateRange(rules.rain_in_hr_upper_bounds, level, "in/hr")}</td>
                      <td>{rateRange(rules.snow_in_hr_upper_bounds, level, "in/hr")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="legend__load">
                {rules.load_rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
