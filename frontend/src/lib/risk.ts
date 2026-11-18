/** Presentation layer for risk levels: colour, label, ordering.
 *
 * The palette is a severity ramp (green -> amber -> orange -> red) with purple
 * reserved for No Travel, matching the convention weather services use for
 * "off the scale" so it never reads as just a darker red.
 */

import type { RiskLevel } from "../types";

export const RISK_LEVELS: RiskLevel[] = ["low", "moderate", "high", "severe", "no_travel"];

export const RISK_COLOR: Record<RiskLevel, string> = {
  low: "#16a34a",
  moderate: "#eab308",
  high: "#f97316",
  severe: "#dc2626",
  no_travel: "#9333ea",
};

export const RISK_LABEL: Record<RiskLevel, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  severe: "Severe",
  no_travel: "No travel",
};

/** Text colour that stays readable on the matching `RISK_COLOR` fill. */
export const RISK_TEXT_ON: Record<RiskLevel, string> = {
  low: "#ffffff",
  moderate: "#422006",
  high: "#431407",
  severe: "#ffffff",
  no_travel: "#ffffff",
};

export function levelFromScore(score: number | null | undefined): RiskLevel | null {
  if (score === null || score === undefined) return null;
  return RISK_LEVELS[Math.max(0, Math.min(RISK_LEVELS.length - 1, Math.round(score)))];
}

export function colorFromScore(score: number | null | undefined): string {
  const level = levelFromScore(score);
  return level ? RISK_COLOR[level] : "#94a3b8";
}

/** Normalised 0-1 intensity for the heat layer. */
export function intensityFromScore(score: number | null | undefined): number {
  if (score === null || score === undefined) return 0;
  return Math.max(0, Math.min(1, score / (RISK_LEVELS.length - 1)));
}
