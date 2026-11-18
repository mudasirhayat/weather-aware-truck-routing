"""API URL map."""

from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("rules", views.rules, name="rules"),
    path("geocode", views.geocode_view, name="geocode"),
    path("plan", views.plan_view, name="plan"),
    path("heatmap", views.heatmap_view, name="heatmap"),
]
