from django.urls import path

from .views import GetProjectView, ProjectLanguageView

urlpatterns = [
    path("projects", GetProjectView.as_view(), name="projects"),
    path("projects/project_language", ProjectLanguageView.as_view(), name="project_language"),
]
