/** Shapes returned by the Django planning API. */

export type RiskLevel = "low" | "moderate" | "high" | "severe" | "no_travel";

export interface Place {
  query: string;
  label: string;
  lat: number;
  lon: number;
}

export interface WeatherReading {
  time: string;
  wind_mph: number;
  gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  precipitation_in_hr: number;
  temperature_c: number | null;
  weather_code: number | null;
}

export interface RiskReading {
  level: RiskLevel;
  level_score: number;
  wind_level: RiskLevel;
  rain_level: RiskLevel;
  snow_level: RiskLevel;
  weather_level: RiskLevel;
  load_rule: string | null;
  escalated_by_load: boolean;
  drivers: string[];
}

export interface Checkpoint {
  index: number;
  lat: number;
  lon: number;
  distance_miles: number;
  eta: string;
  elapsed_hours: number;
  weather: WeatherReading | null;
  risk: RiskReading | null;
  note?: string;
}

export interface RouteMetrics {
  distance_miles: number;
  duration_hours: number;
  miles_by_level: Record<RiskLevel, number>;
  checkpoints_by_level: Record<RiskLevel, number>;
  average_risk: number;
  worst_level: RiskLevel;
  travel_advised: boolean;
  scored_miles: number;
  unknown_weather_miles: number;
}

/** `[lat, lon]` pairs, ready for Leaflet. */
export type LatLngTuple = [number, number];

export interface Route {
  id: string;
  label: string;
  source: string;
  geometry: LatLngTuple[];
  bounds: [LatLngTuple, LatLngTuple];
  arrival: string;
  checkpoint_interval_miles: number;
  checkpoint_interval_coarsened: boolean;
  checkpoints: Checkpoint[];
  metrics: RouteMetrics;
  rank: number;
  recommended: boolean;
}

export interface Recommendation {
  route_id: string;
  route_index: number;
  reason: string;
  travel_advised: boolean;
  ranking: string[];
  criteria: string[];
}

export interface TripPlan {
  plan_id: string;
  request: {
    origin: Place;
    destination: Place;
    depart_at: string;
    load_lb: number;
    interval_miles: number;
  };
  routes: Route[];
  recommendation: Recommendation;
  meta: {
    weather_points_fetched: number;
    weather_points_requested: number;
    forecast_start: string;
    forecast_hours: number;
    elapsed_ms?: number;
    providers: Record<string, string>;
  };
}

export interface HeatmapPoint {
  lat: number;
  lon: number;
  distance_miles: number;
  /** One entry per hour in `timeline`; `null` where no forecast exists. */
  risk: (number | null)[];
  wind_mph: (number | null)[];
  rain_in_hr: (number | null)[];
  snow_in_hr: (number | null)[];
}

export interface Heatmap {
  plan_id: string;
  route_id: string;
  route_label: string;
  anchor: string;
  hours: number;
  timeline: string[];
  levels: RiskLevel[];
  points: HeatmapPoint[];
  meta: { point_count: number; min_spacing_miles: number; load_lb: number; elapsed_ms?: number };
}

export interface RiskRules {
  levels: { name: RiskLevel; score: number }[];
  wind_mph_lower_bounds: { level: RiskLevel; at_or_above: number }[];
  rain_in_hr_upper_bounds: { level: RiskLevel; up_to: number }[];
  snow_in_hr_upper_bounds: { level: RiskLevel; up_to: number }[];
  load_rules: string[];
  recommendation_criteria: string[];
  interval_options_miles: number[];
  max_load_lb: number;
}

export interface TripFormValues {
  origin: string;
  destination: string;
  departAt: string;
  loadLb: number;
  intervalMiles: number;
}
