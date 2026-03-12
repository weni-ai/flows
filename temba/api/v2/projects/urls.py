from django.urls import path

from .views import GetProjectView, InternalProjectMessageCountView, ProjectLanguageView, ProjectMessageCountView

urlpatterns = [
    path("projects", GetProjectView.as_view(), name="projects"),
    path("projects/project_language", ProjectLanguageView.as_view(), name="project_language"),
    path("projects/message_count", ProjectMessageCountView.as_view(), name="project_message_count"),
    path(
        "projects/internal/message_count",
        InternalProjectMessageCountView.as_view(),
        name="internal_project_message_count",
    ),
]
