/** Distance bookkeeping along a route polyline, in miles.
 *
 * Needed to colour a route by risk: the backend reports each checkpoint's
 * distance along the route, and these helpers turn that distance back into a
 * slice of the (decimated) polyline the map actually draws.
 */

import type { Checkpoint, LatLngTuple } from "../types";

const EARTH_RADIUS_MI = 3958.7613;
const RAD = Math.PI / 180;

export function distanceMiles(a: LatLngTuple, b: LatLngTuple): number {
  const p1 = a[0] * RAD;
  const p2 = b[0] * RAD;
  const dp = p2 - p1;
  const dl = (b[1] - a[1]) * RAD;
  const h =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.sqrt(Math.min(1, h)));
}

/** Cumulative distance at each vertex; length is `geometry.length`. */
export function cumulativeMiles(geometry: LatLngTuple[]): number[] {
  const out = new Array<number>(geometry.length);
  out[0] = 0;
  for (let i = 1; i < geometry.length; i += 1) {
    out[i] = out[i - 1] + distanceMiles(geometry[i - 1], geometry[i]);
  }
  return out;
}

/** Index of the last vertex at or before `miles`. */
export function indexAtMiles(cumulative: number[], miles: number): number {
  let low = 0;
  let high = cumulative.length - 1;
  while (low < high) {
    const mid = (low + high + 1) >> 1;
    if (cumulative[mid] <= miles) low = mid;
    else high = mid - 1;
  }
  return low;
}

export interface ColoredSegment {
  key: string;
  level: string;
  positions: LatLngTuple[];
}

/**
 * Split a route into polyline slices coloured by checkpoint risk.
 *
 * Each checkpoint owns the stretch from the midpoint behind it to the midpoint
 * ahead - the same attribution the backend uses for "severe miles", so the map
 * and the numbers always agree. Consecutive stretches at the same level are
 * merged, which turns ~160 checkpoints into a handful of polylines.
 */
export function colorRouteByRisk(
  geometry: LatLngTuple[],
  checkpoints: Checkpoint[],
): ColoredSegment[] {
  if (geometry.length < 2 || checkpoints.length === 0) return [];

  const cumulative = cumulativeMiles(geometry);
  const total = cumulative[cumulative.length - 1];
  const reported = checkpoints[checkpoints.length - 1].distance_miles || total;
  // The drawn polyline is decimated, so its measured length drifts slightly
  // from the routing engine's. Scale checkpoint distances onto it.
  const scale = reported > 0 ? total / reported : 1;

  const bounds = checkpoints.map((checkpoint, i) => {
    const previous = checkpoints[i - 1]?.distance_miles ?? checkpoint.distance_miles;
    const next = checkpoints[i + 1]?.distance_miles ?? checkpoint.distance_miles;
    return {
      level: checkpoint.risk?.level ?? "unknown",
      from: i === 0 ? 0 : ((previous + checkpoint.distance_miles) / 2) * scale,
      to:
        i === checkpoints.length - 1
          ? total
          : ((checkpoint.distance_miles + next) / 2) * scale,
    };
  });

  // Merge neighbouring stretches that share a level.
  const merged: typeof bounds = [];
  for (const span of bounds) {
    const last = merged[merged.length - 1];
    if (last && last.level === span.level) last.to = span.to;
    else merged.push({ ...span });
  }

  return merged.map((span, i) => {
    const startIndex = indexAtMiles(cumulative, span.from);
    const endIndex = indexAtMiles(cumulative, span.to);
    const positions = geometry.slice(startIndex, Math.max(endIndex + 1, startIndex + 2));
    return { key: `${span.level}-${i}`, level: span.level, positions };
  });
}
