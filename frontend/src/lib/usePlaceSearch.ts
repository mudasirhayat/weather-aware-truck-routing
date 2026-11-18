/** Debounced place lookup for the origin/destination typeahead. */

import { useEffect, useState } from "react";

import { searchPlaces } from "../api/client";
import type { Place } from "../types";

const DEBOUNCE_MS = 350;
const MIN_LENGTH = 3;

export function usePlaceSearch(query: string, enabled: boolean): Place[] {
  const [results, setResults] = useState<Place[]>([]);

  useEffect(() => {
    const text = query.trim();
    if (!enabled || text.length < MIN_LENGTH) {
      setResults([]);
      return;
    }

    const controller = new AbortController();
    // Nominatim asks callers to go easy; debouncing keeps us to one request per
    // pause in typing rather than one per keystroke.
    const timer = window.setTimeout(() => {
      searchPlaces(text, controller.signal)
        .then((body) => {
          if (!controller.signal.aborted) setResults(body.results);
        })
        .catch(() => {
          if (!controller.signal.aborted) setResults([]);
        });
    }, DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, enabled]);

  return results;
}
