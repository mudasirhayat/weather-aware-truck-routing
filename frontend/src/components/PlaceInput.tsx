/** Text input with a debounced place-name typeahead. */

import { useId, useState } from "react";

import { usePlaceSearch } from "../lib/usePlaceSearch";

interface PlaceInputProps {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}

export function PlaceInput({ label, value, placeholder, onChange }: PlaceInputProps) {
  const id = useId();
  const [focused, setFocused] = useState(false);
  // Suppress the dropdown right after a pick so it doesn't reopen on the
  // suggestion we just chose. State rather than a ref because it is read
  // during render to decide whether the lookup runs.
  const [justPicked, setJustPicked] = useState(false);
  const suggestions = usePlaceSearch(value, focused && !justPicked);

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="field__combo">
        <input
          id={id}
          type="text"
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          onChange={(event) => {
            setJustPicked(false);
            onChange(event.target.value);
          }}
          onFocus={() => setFocused(true)}
          // Delay so a click on a suggestion registers before the list closes.
          onBlur={() => window.setTimeout(() => setFocused(false), 150)}
        />
        {focused && suggestions.length > 0 && (
          <ul className="field__suggestions">
            {suggestions.map((place) => (
              <li key={`${place.lat},${place.lon}`}>
                <button
                  type="button"
                  onClick={() => {
                    setJustPicked(true);
                    onChange(place.label);
                    setFocused(false);
                  }}
                >
                  {place.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
