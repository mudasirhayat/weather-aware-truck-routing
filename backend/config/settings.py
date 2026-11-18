"""Django settings for the weather-aware truck routing API.

Everything environment-specific is read from env vars with sane local defaults,
so the same image runs locally and on a host like Render/Fly/Railway.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me-in-production"
)
DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver")
if not DEBUG and not env_list("DJANGO_ALLOWED_HOSTS"):
    # Fail safe on a platform that injects its own hostname.
    ALLOWED_HOSTS = ["*"]

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # No auth/admin/contenttypes: the service is stateless and has no database.
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.gzip.GZipMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# The API is stateless and computes everything from upstream services, so there
# is no database to configure.
DATABASES = {}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# The built React app. WhiteNoise serves its hashed assets straight from here,
# so one process serves both the API and the UI.
FRONTEND_DIST = Path(
    os.environ.get("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist")
).resolve()
def _is_immutable_asset(path: str, url: str) -> bool:
    """Vite writes content-hashed filenames, so those can cache forever.

    WhiteNoise only infers this from Django's staticfiles manifest, which does
    not cover files served straight out of the Vite build, hence the explicit
    test. index.html must stay mutable or deploys would never be picked up.
    """
    return bool(re.match(r"^/assets/.+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$", url))


if FRONTEND_DIST.is_dir():
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = False
    WHITENOISE_IMMUTABLE_FILE_TEST = _is_immutable_asset
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "routing.exceptions.api_exception_handler",
}
if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer"
    )

CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
)
CORS_ALLOW_ALL_ORIGINS = env_bool("DJANGO_CORS_ALLOW_ALL", DEBUG)

# --------------------------------------------------------------------------
# Caching - upstream responses are reused aggressively. Routes and forecasts
# for the same inputs do not change minute to minute, and the free providers
# we use ask callers to be considerate.
# --------------------------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "routing-cache",
            "OPTIONS": {"MAX_ENTRIES": 4096, "CULL_FREQUENCY": 4},
        }
    }

# --------------------------------------------------------------------------
# Provider configuration
# --------------------------------------------------------------------------
OUTBOUND_USER_AGENT = os.environ.get(
    "OUTBOUND_USER_AGENT",
    "weather-aware-truck-routing/1.0 (take-home assessment)",
)

OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
OSRM_PROFILE = os.environ.get("OSRM_PROFILE", "driving")

GEOCODE_TIMEOUT_SECONDS = env_float("GEOCODE_TIMEOUT_SECONDS", 10.0)
ROUTING_TIMEOUT_SECONDS = env_float("ROUTING_TIMEOUT_SECONDS", 25.0)
WEATHER_TIMEOUT_SECONDS = env_float("WEATHER_TIMEOUT_SECONDS", 25.0)

GEOCODE_CACHE_SECONDS = env_int("GEOCODE_CACHE_SECONDS", 7 * 24 * 3600)
ROUTING_CACHE_SECONDS = env_int("ROUTING_CACHE_SECONDS", 24 * 3600)
WEATHER_CACHE_SECONDS = env_int("WEATHER_CACHE_SECONDS", 15 * 60)

# --------------------------------------------------------------------------
# Planning limits
# --------------------------------------------------------------------------
MAX_ROUTE_OPTIONS = env_int("MAX_ROUTE_OPTIONS", 3)
HEATMAP_MAX_POINTS = env_int("HEATMAP_MAX_POINTS", 70)
HEATMAP_MIN_SPACING_MILES = env_float("HEATMAP_MIN_SPACING_MILES", 5.0)
HEATMAP_HOURS = env_int("HEATMAP_HOURS", 48)
MAX_LOAD_LB = env_float("MAX_LOAD_LB", 200_000.0)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
