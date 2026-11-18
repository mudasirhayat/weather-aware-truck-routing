# Single-image build: compile the React app, then serve it and the API from
# one Django process. One service to deploy, no CORS to configure.

# ---------------------------------------------------------------- frontend
FROM node:22-alpine AS frontend

WORKDIR /app/frontend
# Copy manifests first so `npm ci` is cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ----------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Pre-compress the bundle so WhiteNoise can serve .gz without per-request work,
# then collect Django's own static files.
RUN python -m whitenoise.compress frontend/dist \
    && python backend/manage.py collectstatic --noinput

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000

# Threads (not just processes) because a plan is almost entirely time spent
# waiting on the routing and weather APIs.
CMD gunicorn config.wsgi:application \
    --chdir backend \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --threads "${WEB_THREADS:-8}" \
    --worker-class gthread \
    --timeout 120 \
    --access-logfile -
