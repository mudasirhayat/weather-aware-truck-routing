/** Planning state machine: submit a trip, track status, expose the result. */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, planTrip } from "../api/client";
import type { TripFormValues, TripPlan } from "../types";

type Status = "idle" | "loading" | "ready" | "error";

export interface TripPlanState {
  status: Status;
  plan: TripPlan | null;
  error: string | null;
  submit: (values: TripFormValues) => void;
  reset: () => void;
}

export function useTripPlan(): TripPlanState {
  const [status, setStatus] = useState<Status>("idle");
  const [plan, setPlan] = useState<TripPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  // Abandon any outstanding request when the component goes away.
  useEffect(() => () => inFlight.current?.abort(), []);

  const submit = useCallback((values: TripFormValues) => {
    // A new search supersedes the old one; cancel it so a slow earlier
    // response can never overwrite a newer plan.
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setStatus("loading");
    setError(null);

    planTrip(values, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setPlan(result);
        setStatus("ready");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          cause instanceof ApiError ? cause.message : "Could not plan this trip.",
        );
        setStatus("error");
      });
  }, []);

  const reset = useCallback(() => {
    inFlight.current?.abort();
    setPlan(null);
    setError(null);
    setStatus("idle");
  }, []);

  return { status, plan, error, submit, reset };
}
