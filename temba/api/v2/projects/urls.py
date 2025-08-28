from django.urls import path

from .views import GetProjectView

urlpatterns = [
    path("projects", GetProjectView.as_view(), name="projects"),
]
