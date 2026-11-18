/** Trip inputs: where, when, how heavy, and how finely to sample. */

import { useState } from "react";

import { formatPounds, nextHour, toLocalInputValue } from "../lib/format";
import type { TripFormValues } from "../types";
import { PlaceInput } from "./PlaceInput";

interface TripFormProps {
  onSubmit: (values: TripFormValues) => void;
  loading: boolean;
  intervalOptions: number[];
}

const EXAMPLES: { label: string; values: Partial<TripFormValues> }[] = [
  { label: "Denver → Salt Lake City", values: { origin: "Denver, CO", destination: "Salt Lake City, UT" } },
  { label: "Chicago → Denver", values: { origin: "Chicago, IL", destination: "Denver, CO" } },
  { label: "Seattle → Billings", values: { origin: "Seattle, WA", destination: "Billings, MT" } },
];

export function TripForm({ onSubmit, loading, intervalOptions }: TripFormProps) {
  const [values, setValues] = useState<TripFormValues>({
    origin: "Denver, CO",
    destination: "Salt Lake City, UT",
    departAt: toLocalInputValue(nextHour()),
    loadLb: 42000,
    intervalMiles: 25,
  });

  const update = <K extends keyof TripFormValues>(key: K, value: TripFormValues[K]) =>
    setValues((current) => ({ ...current, [key]: value }));

  const invalid =
    !values.origin.trim() || !values.destination.trim() || !values.departAt;

  return (
    <form
      className="trip-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!invalid && !loading) onSubmit(values);
      }}
    >
      <PlaceInput
        label="Origin"
        value={values.origin}
        placeholder="City, state or lat, lon"
        onChange={(value) => update("origin", value)}
      />
      <PlaceInput
        label="Destination"
        value={values.destination}
        placeholder="City, state or lat, lon"
        onChange={(value) => update("destination", value)}
      />

      <div className="field">
        <label htmlFor="depart-at">Departure</label>
        <input
          id="depart-at"
          type="datetime-local"
          value={values.departAt}
          onChange={(event) => update("departAt", event.target.value)}
        />
      </div>

      <div className="field">
        <label htmlFor="load-lb">
          Load weight <span className="field__hint">{formatPounds(values.loadLb)}</span>
        </label>
        <input
          id="load-lb"
          type="range"
          min={0}
          max={80000}
          step={1000}
          value={values.loadLb}
          onChange={(event) => update("loadLb", Number(event.target.value))}
        />
        <div className="field__scale">
          <span>empty</span>
          <span>30k</span>
          <span>40k</span>
          <span>80k</span>
        </div>
      </div>

      <fieldset className="field field--inline">
        <legend>Checkpoint interval</legend>
        <div className="segmented">
          {intervalOptions.map((miles) => (
            <button
              key={miles}
              type="button"
              className={values.intervalMiles === miles ? "is-active" : ""}
              aria-pressed={values.intervalMiles === miles}
              onClick={() => update("intervalMiles", miles)}
            >
              {miles} mi
            </button>
          ))}
        </div>
      </fieldset>

      <button className="button button--primary" type="submit" disabled={invalid || loading}>
        {loading ? "Planning…" : "Plan route"}
      </button>

      <div className="examples">
        <span>Try:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example.label}
            type="button"
            className="link"
            onClick={() => setValues((current) => ({ ...current, ...example.values }))}
          >
            {example.label}
          </button>
        ))}
      </div>
    </form>
  );
}
