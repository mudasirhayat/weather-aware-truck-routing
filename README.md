# Weather-Aware Truck Routing

Plan a truck trip against the weather it will actually meet. The app generates
three route options, samples the forecast at every checkpoint **using the
truck's predicted arrival time at that point**, scores each checkpoint with the
wind/rain/snow and load rules, and recommends the route that balances risk
against travel time.

**Stack:** Django 5 + Django REST Framework · React 19 + TypeScript + Vite ·
Leaflet. No API keys required.

---

## Quick start

Two terminals, or use Docker below.

```bash
# 1. Backend  (http://127.0.0.1:8000)
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python manage.py runserver

# 2. Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to Django, so
there is nothing else to configure.

### Docker (single service, as deployed)

```bash
docker build -t truck-routing .
docker run -p 8000:8000 truck-routing
# http://localhost:8000  - serves the built UI and the API together
```

### Tests

```bash
cd backend && ./.venv/bin/python manage.py test routing   # 107 tests
cd frontend && npx tsc --noEmit -p tsconfig.app.json && npm run build
```

---

## How it works

```
   Origin / destination / departure / load weight
                      │
                      ▼
            ┌──────────────────┐
            │ Geocode          │  Nominatim  (literal "lat, lon" skips the call)
            └────────┬─────────┘
                     ▼
            ┌──────────────────┐
            │ 3 route options  │  OSRM alternatives, topped up with
            └────────┬─────────┘  via-point detours, de-duplicated
                     ▼
            ┌──────────────────┐
            │ Checkpoints      │  every 10/25/50 mi, ETA from the engine's
            └────────┬─────────┘  real per-segment durations
                     ▼
            ┌──────────────────┐
            │ Forecast         │  Open-Meteo, every point of every route in
            └────────┬─────────┘  ONE batched, de-duplicated request
                     ▼
            ┌──────────────────┐
            │ Risk + ranking   │  thresholds -> load rules -> severe-mile
            └────────┬─────────┘  comparison
                     ▼
              Map, route cards, corridor heatmap
```

### Risk rules

Implemented in [`backend/routing/risk.py`](backend/routing/risk.py), which is
pure (no I/O, no Django) so every threshold in the brief is directly
unit-tested.

|       | Low | Moderate | High | Severe | No Travel |
|-------|-----|----------|------|--------|-----------|
| Wind  | <25 mph | 25–34 | 35–44 | 45–54 | ≥55 mph |
| Rain  | <0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow  | <0.5 in/hr | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

Load rules, applied on top (they can raise a level, never lower it):

* ≥55 mph → **No Travel** at any load
* 45–54 mph **and** >30,000 lb → **No Travel**
* 35–44 mph **and** >40,000 lb → **Severe**

A checkpoint's level is the worst of its three conditions, then raised by
whichever load rule fires. The API returns *why* — which condition drove the
level, and whether the load escalated it.

**Two readings the brief leaves open, resolved explicitly:**

1. *Wind bands have integer endpoints* ("25–34", then "35–44"), so 34.5 mph is
   unlabelled. Wind is treated as continuous with inclusive lower bounds:
   `[25,35)` Moderate, `[35,45)` High, `[45,55)` Severe.
2. *Rain and snow bands share endpoints* ("0.10–0.25", then "0.25–0.50"). The
   shared value goes to the **lower** band, so 0.25 in/hr is Moderate and 0.50
   in/hr is High.

Load thresholds are read strictly as written: `>30,000 lb` means exactly
30,000 lb does **not** trigger the rule.

### Route recommendation

The brief's order, lowest-first:

1. Fewest **Severe** miles
2. Fewest **High** miles
3. Lowest **average risk**
4. Shortest **travel time**

**One addition:** *No Travel* miles are compared **before** Severe miles. A No
Travel checkpoint means the truck cannot safely or legally pass, which is
strictly worse than Severe, and the brief's own table ranks it above Severe.
Routes containing any are flagged `travel_advised: false` and the UI warns
instead of silently recommending an impassable road. The full criteria list is
returned in every response and shown in the sidebar, so the ranking is never a
black box.

**"Severe miles" is a distance, not a sample count.** Each checkpoint owns the
stretch from the midpoint behind it to the midpoint ahead, so attributed miles
sum exactly to the route length and no stretch is double-counted. The map
colours each stretch with the same attribution, so the line and the numbers
always agree.

### ETAs

Checkpoint arrival times come from OSRM's **per-segment durations**, not from
`distance / average speed`. Requesting `overview=full` with
`annotations=distance,duration` returns one duration per polyline segment, so a
checkpoint 50 miles in gets a time that reflects the real speed profile —
crawling out of a city, then running at highway speed. For a via-point route
the per-leg annotations are concatenated, which lines up with the overview
geometry because consecutive legs share their boundary node. If annotations are
ever missing or misaligned, it falls back to spreading the reported duration
across the measured polyline.

### Getting three genuinely different routes

OSRM's `alternatives` parameter is best-effort — on many corridors it returns
one or two roads, not three. When it comes up short, the app synthesises
candidates by routing through a **via-point offset perpendicular to the direct
line** (scaled to trip length), the way a dispatcher would say "go round the
north side". Candidates are de-duplicated by comparing the coarse grid cells
each polyline passes through (Jaccard overlap >0.72 ⇒ same road), and detours
more than 2.2× the fastest route are discarded. The fill-in requests run
concurrently, so the guarantee costs one round-trip of latency, not six.

---

## Performance

The expensive part is network I/O to free third-party APIs, so the work went
into doing less of it.

| Technique | Effect |
|---|---|
| **Batched forecasts** — Open-Meteo accepts comma-separated coordinate lists | every checkpoint on all three routes in **one** request, not ~36 |
| **Spatial de-duplication** — checkpoints snapped to a ~1 km grid | typically removes a third of points (routes share endpoints; 10-mile sampling oversamples the model's own resolution) |
| **Whole-series heatmap** — all 49 hours returned in one response | scrubbing the 0–48h slider is local indexing: **no request per frame** |
| **Concurrent via-point routing** | 3-route guarantee costs one round-trip, not six |
| **Response caching** — forecasts 15 min, routes 24 h, geocodes 7 days | repeat plans are near-instant; also keeps us polite to free endpoints |
| **Polyline decimation** — ~5,000 points → ≤700 before transport | indistinguishable at map zooms, much smaller payload and faster panning |
| **Canvas rendering** (`preferCanvas`) | hundreds of checkpoint markers stay smooth while panning |
| **Checkpoint cap** (160/route) | a 3,000-mile trip at a 10-mile interval widens the interval instead of making 300 lookups — and says so in the UI |
| **Pre-compressed, immutable assets** | 25 KB JS → 8.7 KB over the wire; hashed files cached forever, `index.html` never |

A cold Denver → Salt Lake City plan (3 routes, 36 checkpoints) takes ~5 s,
almost all of it waiting on OSRM; warm, it is ~0.1 s.

### The heatmap

Written as a small custom canvas layer rather than using `leaflet.heat`,
because that library **adds** overlapping point intensities — a long run of
merely "moderate" weather sums into a red blob and misreports the risk. Here
each sample is drawn as a radial falloff in its own risk colour, painted in
ascending severity order, so where blobs overlap the **worse** condition wins —
the same rule the risk engine uses. Repaints are coalesced into one
`requestAnimationFrame`, and off-screen samples are culled.

---

## API

Base URL `/api`. Errors are always `{"error": {"detail": "...", "source": "..."}}`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness probe |
| `GET /rules` | the thresholds the engine is enforcing — the UI legend reads these so it can't drift from the code |
| `GET /geocode?q=&limit=` | typeahead place lookup |
| `POST /plan` | plan a trip |
| `GET /heatmap?plan_id=&route_id=&hours=` | corridor series for the slider |

```bash
curl -X POST localhost:8000/api/plan -H 'Content-Type: application/json' -d '{
  "origin": "Casper, WY",
  "destination": "Rapid City, SD",
  "depart_at": "2026-11-18T12:00:00Z",
  "load_lb": 45000,
  "interval_miles": 25
}'
```

Returns each route with its geometry, every checkpoint (position, ETA, weather,
risk level and the drivers behind it), `miles_by_level`, `average_risk`,
`worst_level`, `travel_advised`, a `rank`, and a plain-English `reason` for the
recommendation. `plan_id` is then used for the heatmap.

Status codes distinguish fault: `400` invalid input, `422` the request was fine
but unanswerable (unknown place, expired plan), `502/503/504` an upstream
service failed.

---

## Design decisions

**Keyless providers.** OSRM (routing), Nominatim (geocoding) and Open-Meteo
(weather) were chosen so the app runs and deploys with zero secrets — a
reviewer can clone and run it. Each sits behind a thin adapter in
`backend/routing/providers/`, so swapping in a keyed provider (ORS, Mapbox,
Google) is a single-file change. `OSRM_BASE_URL` can point at your own OSRM
instance, including a truck-profile build.

**Known limitation:** the public OSRM demo server uses a *car* profile. It has
no truck weight/height/bridge restrictions and no HOS rest stops, so distances
and durations are car-realistic, not truck-realistic. The risk engine, the
sampling and the ranking are unaffected — point `OSRM_BASE_URL` at a truck
profile and the numbers become truck numbers.

**Missing forecasts are not assumed safe.** If a checkpoint's ETA falls outside
the forecast window, its miles are reported as `unknown_weather_miles` and
excluded from the average rather than silently scored Low.

**Wind is classified on sustained speed**, as the brief's table specifies.
Gusts are fetched and shown in the checkpoint popup as context, but never
change a level.

**The slider is anchored on departure**, not "now" — hour 0 is when the truck
rolls, which is the window a dispatcher cares about. Absolute timestamps are
labelled throughout.

**No database.** Every answer is computed from upstream services; plans live in
the cache for an hour so the heatmap endpoint can reuse the geometry instead of
the client posting a 5,000-point polyline back. Set `REDIS_URL` to share that
cache across workers; without it, an in-process LocMem cache is used.

---

## Layout

```
backend/
  routing/
    risk.py          thresholds + load rules   (pure, heavily tested)
    scoring.py       mile attribution, ranking (pure)
    sampling.py      checkpoints + ETAs        (pure)
    geo.py           great-circle geometry     (pure)
    services.py      orchestration
    providers/       geocoding · routing_osrm · weather · base (retries, cache)
    tests/           107 tests
  config/            settings, urls
frontend/src/
  components/        MapView · HeatLayer · TripForm · RouteCard · CheckpointTable · TimeSlider · Legend
  lib/               risk palette · formatting · polyline maths · hooks
  api/client.ts      typed fetch wrapper
```

The pure modules hold all the domain logic and have no Django or network
imports, which is what makes the rule tests fast and exact.

## Configuration

Every setting has a working default; see [`.env.example`](.env.example). The
one worth setting in production is `OUTBOUND_USER_AGENT`, which identifies your
deployment to the free upstream APIs as their usage policies ask.

## Deploying

`render.yaml` is a ready Render blueprint; the `Dockerfile` runs anywhere that
takes a container (Fly, Railway, Cloud Run). The image builds the frontend,
pre-compresses it, and serves UI and API from one Gunicorn process — one
service, no CORS, no second host.

## Attribution

Routing © [OSRM](http://project-osrm.org/) · Geocoding and map tiles ©
[OpenStreetMap](https://www.openstreetmap.org/copyright) contributors ·
Forecasts © [Open-Meteo](https://open-meteo.com/).
