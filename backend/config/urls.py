"""Root URL configuration.

`/api/...` is the JSON API; everything else falls through to the built React
app (or a JSON service descriptor when the frontend has not been built).
"""

from django.urls import include, path, re_path

from routing.spa import spa

urlpatterns = [
    path("api/", include("routing.urls")),
    # Anything that is not an API route is the SPA's problem, not a 404.
    re_path(r"^(?!api/).*$", spa, name="spa"),
]
