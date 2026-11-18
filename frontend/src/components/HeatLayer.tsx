/**
 * Corridor risk heatmap drawn on a canvas in Leaflet's overlay pane.
 *
 * Why not leaflet.heat: that library *adds* overlapping point intensities, so a
 * long run of merely "moderate" weather sums into a red blob and lies about the
 * risk. Here each sample is drawn as a radial falloff in its own risk colour,
 * painted in ascending severity order, so where blobs overlap the worse
 * condition wins - which is the same rule the risk engine uses.
 *
 * Only one hour is drawn at a time; the full series is already in memory, so
 * moving the slider is a canvas repaint with no network and no re-layout.
 */

import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";

import { RISK_COLOR, RISK_LEVELS } from "../lib/risk";
import type { HeatmapPoint } from "../types";

interface HeatLayerProps {
  points: HeatmapPoint[];
  /** Index into each point's hourly arrays. */
  hourIndex: number;
  opacity?: number;
}

/** Radius bounds in pixels, so the band neither vanishes nor swamps the map. */
const MIN_RADIUS_PX = 16;
const MAX_RADIUS_PX = 160;

/**
 * `#rrggbb` -> `rgba(r, g, b, alpha)`.
 *
 * Gradient stops interpolate in straight (non-premultiplied) RGBA, so fading a
 * colour to the keyword `transparent` fades it through transparent *black* and
 * leaves a dirty halo. Fading to the same hue at zero alpha stays clean.
 */
function withAlpha(hex: string, alpha: number): string {
  const value = parseInt(hex.slice(1), 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function medianSpacing(pixels: L.Point[]): number {
  if (pixels.length < 2) return 48;
  const gaps: number[] = [];
  for (let i = 1; i < pixels.length; i += 1) {
    gaps.push(pixels[i].distanceTo(pixels[i - 1]));
  }
  gaps.sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)] || 48;
}

export function HeatLayer({ points, hourIndex, opacity = 0.72 }: HeatLayerProps) {
  const map = useMap();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const scheduleRef = useRef<(() => void) | null>(null);
  // Held in a ref so pan/zoom handlers always read current data without being
  // re-bound on every slider tick. Written in an effect rather than during
  // render, which a concurrent re-render could otherwise discard.
  const dataRef = useRef({ points, hourIndex, opacity });

  // Create the canvas once and keep it alive across data changes.
  useEffect(() => {
    const canvas = L.DomUtil.create("canvas", "risk-heat-canvas") as HTMLCanvasElement;
    canvas.style.position = "absolute";
    canvas.style.pointerEvents = "none";
    canvas.style.willChange = "transform";
    map.getPanes().overlayPane.appendChild(canvas);
    canvasRef.current = canvas;

    const draw = () => {
      frameRef.current = null;
      const element = canvasRef.current;
      if (!element) return;

      const size = map.getSize();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      if (element.width !== size.x * ratio || element.height !== size.y * ratio) {
        element.width = size.x * ratio;
        element.height = size.y * ratio;
        element.style.width = `${size.x}px`;
        element.style.height = `${size.y}px`;
      }
      // Keep the canvas pinned to the viewport while the pane is translated.
      L.DomUtil.setPosition(element, map.containerPointToLayerPoint([0, 0]));

      const ctx = element.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, size.x, size.y);

      const { points: data, hourIndex: hour, opacity: alpha } = dataRef.current;
      if (!data.length) return;

      const projected = data.map((point) => map.latLngToContainerPoint([point.lat, point.lon]));
      const radius = Math.max(
        MIN_RADIUS_PX,
        Math.min(MAX_RADIUS_PX, medianSpacing(projected) * 0.95),
      );

      // Cull offscreen samples - panning away from the corridor costs nothing.
      const margin = radius * 1.5;
      const visible = data
        .map((point, i) => ({ point, at: projected[i] }))
        .filter(
          ({ at }) =>
            at.x > -margin && at.y > -margin && at.x < size.x + margin && at.y < size.y + margin,
        );

      ctx.globalAlpha = alpha;
      // Ascending severity: worse weather is painted last and therefore wins.
      for (let level = 0; level < RISK_LEVELS.length; level += 1) {
        const color = RISK_COLOR[RISK_LEVELS[level]];
        for (const { point, at } of visible) {
          if (point.risk[hour] !== level) continue;
          const gradient = ctx.createRadialGradient(at.x, at.y, 0, at.x, at.y, radius);
          gradient.addColorStop(0, color);
          gradient.addColorStop(0.55, color);
          gradient.addColorStop(1, withAlpha(color, 0));
          ctx.fillStyle = gradient;
          ctx.beginPath();
          ctx.arc(at.x, at.y, radius, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    };

    const schedule = () => {
      if (frameRef.current === null) {
        frameRef.current = window.requestAnimationFrame(draw);
      }
    };

    // `move` fires continuously while panning; coalescing into one frame per
    // repaint is what keeps dragging smooth.
    scheduleRef.current = schedule;
    map.on("move zoom viewreset resize zoomend moveend", schedule);
    schedule();

    return () => {
      scheduleRef.current = null;
      map.off("move zoom viewreset resize zoomend moveend", schedule);
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
        // Must clear the handle too: schedule() treats a non-null frameRef as
        // "a repaint is already queued", so leaving a cancelled id here would
        // silently suppress every future draw after a remount.
        frameRef.current = null;
      }
      canvas.remove();
      canvasRef.current = null;
    };
  }, [map]);

  // Repaint when the hour or the data changes, without disturbing other layers.
  useEffect(() => {
    dataRef.current = { points, hourIndex, opacity };
    scheduleRef.current?.();
  }, [points, hourIndex, opacity]);

  return null;
}
