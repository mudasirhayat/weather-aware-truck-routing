/** Typed wrapper around the planning API, with a readable error type. */

import type { Heatmap, Place, RiskRules, TripFormValues, TripPlan } from "../types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly source: string;

  constructor(message: string, status: number, source = "api") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.source = source;
  }
}

/** Flatten DRF's `{field: [msg]}` validation payloads into one line. */
function readDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(readDetail).join(" ");
  if (detail && typeof detail === "object") {
    return Object.entries(detail as Record<string, unknown>)
      .map(([field, value]) => `${field}: ${readDetail(value)}`)
      .join(" · ");
  }
  return "Something went wrong.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(
      "Could not reach the planning service. Is the backend running?",
      0,
      "network",
    );
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    let source = "api";
    try {
      const body = await response.json();
      if (body?.error) {
        message = readDetail(body.error.detail);
        source = body.error.source ?? source;
      }
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(message, response.status, source);
  }

  return (await response.json()) as T;
}

export function planTrip(values: TripFormValues, signal?: AbortSignal): Promise<TripPlan> {
  return request<TripPlan>("/plan", {
    method: "POST",
    signal,
    body: JSON.stringify({
      origin: values.origin,
      destination: values.destination,
      // `datetime-local` has no zone; the driver means their own clock, so send
      // the browser's offset rather than letting the server assume UTC.
      depart_at: new Date(values.departAt).toISOString(),
      load_lb: values.loadLb,
      interval_miles: values.intervalMiles,
    }),
  });
}

export function fetchHeatmap(
  planId: string,
  routeId: string,
  hours = 48,
  signal?: AbortSignal,
): Promise<Heatmap> {
  const query = new URLSearchParams({ plan_id: planId, route_id: routeId, hours: String(hours) });
  return request<Heatmap>(`/heatmap?${query}`, { signal });
}

export function fetchRules(signal?: AbortSignal): Promise<RiskRules> {
  return request<RiskRules>("/rules", { signal });
}

export function searchPlaces(
  query: string,
  signal?: AbortSignal,
): Promise<{ results: Place[] }> {
  const params = new URLSearchParams({ q: query, limit: "5" });
  return request<{ results: Place[] }>(`/geocode?${params}`, { signal });
}
