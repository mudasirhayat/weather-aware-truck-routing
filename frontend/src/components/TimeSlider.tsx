/** 0-48 hour forecast scrubber for the corridor heatmap, with playback. */

import { useEffect, useRef } from "react";

import { formatFull } from "../lib/format";

interface TimeSliderProps {
  timeline: string[];
  hour: number;
  onChange: (hour: number) => void;
  playing: boolean;
  onTogglePlay: () => void;
  disabled?: boolean;
}

const FRAME_MS = 420;

export function TimeSlider({
  timeline,
  hour,
  onChange,
  playing,
  onTogglePlay,
  disabled,
}: TimeSliderProps) {
  const last = Math.max(0, timeline.length - 1);
  // Keep the latest hour in a ref so the interval never needs re-creating,
  // which would make playback stutter.
  const hourRef = useRef(hour);
  useEffect(() => {
    hourRef.current = hour;
  }, [hour]);

  useEffect(() => {
    if (!playing || disabled || last === 0) return;
    const timer = window.setInterval(() => {
      onChange((hourRef.current + 1) % (last + 1));
    }, FRAME_MS);
    return () => window.clearInterval(timer);
  }, [playing, disabled, last, onChange]);

  const label = timeline[hour] ? formatFull(timeline[hour]) : "—";

  return (
    <div className="time-slider">
      <button
        className="button button--icon"
        type="button"
        onClick={onTogglePlay}
        disabled={disabled}
        aria-label={playing ? "Pause forecast animation" : "Play forecast animation"}
      >
        {playing ? "❚❚" : "▶"}
      </button>

      <div className="time-slider__body">
        <div className="time-slider__labels">
          <strong>{label}</strong>
          <span>
            +{hour}h of {last}h
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={last}
          step={1}
          value={hour}
          disabled={disabled}
          aria-label="Forecast hour"
          onChange={(event) => onChange(Number(event.target.value))}
        />
      </div>
    </div>
  );
}
