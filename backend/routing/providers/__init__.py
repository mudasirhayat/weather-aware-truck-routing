"""Third-party service adapters (geocoding, routing, weather).

Each provider is a thin, swappable adapter. The brief allows third-party APIs,
so the defaults are chosen to need **no API keys**: OSRM for routing, Nominatim
for geocoding, Open-Meteo for weather. Swapping in a keyed provider (ORS,
Mapbox, Google) means implementing the same small surface used by
``routing.services``.
"""

from .base import NotFound, ProviderError, ProviderTimeout, ProviderUnavailable

__all__ = ["NotFound", "ProviderError", "ProviderTimeout", "ProviderUnavailable"]
