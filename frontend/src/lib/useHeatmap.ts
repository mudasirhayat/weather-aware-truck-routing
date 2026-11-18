/** Loads the 0-48h corridor heatmap for one route.
 *
 * The whole time series arrives in a single response, so moving the hour slider
 * is pure local indexing - no request per frame, which is what keeps the
 * animation smooth.
 */

import { useEffect, useState } from "react";

import { ApiError, fetchHeatmap } from "../api/client";
import type { Heatmap } from "../types";

export interface HeatmapState {
  heatmap: Heatmap | null;
  loading: boolean;
  error: string | null;
}

export function useHeatmap(
  planId: string | null,
  routeId: string | null,
  hours = 48,
  enabled = true,
): HeatmapState {
  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !planId || !routeId) {
      setHeatmap(null);
      setError(null);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);

    fetchHeatmap(planId, routeId, hours, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setHeatmap(result);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setHeatmap(null);
        setError(
          cause instanceof ApiError ? cause.message : "Could not load the heatmap.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [planId, routeId, hours, enabled]);

  return { heatmap, loading, error };
}
