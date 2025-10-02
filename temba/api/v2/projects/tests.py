import uuid
from functools import wraps
from unittest.mock import patch

from rest_framework.authentication import BasicAuthentication

from django.test import SimpleTestCase, override_settings
from django.urls import resolve, reverse

from temba.api.v2.projects.views import GetProjectView, ProjectLanguageView
from temba.tests import TembaTest

GET_PROJECT_VIEW_PATH = "temba.api.v2.projects.views.GetProjectView"


def skip_auth_and_permissions(view_path: str):
    """
    Decorator to disable authentication and permission checks for a specific endpoint class.
    Use when testing view logic (status codes and payload) without auth side-effects.
    """

    def decorator(func):
        @patch(f"{view_path}.authentication_classes", [])
        @patch(f"{view_path}.permission_classes", [])
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


class GetProjectViewTest(TembaTest):
    def setUp(self):
        super().setUp()

        # Ensure org has a project UUID for lookups
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

        self.url = reverse("api.v2.projects")

    @patch(f"{GET_PROJECT_VIEW_PATH}.authentication_classes", [BasicAuthentication])
    def test_requires_authentication(self):
        # Without authentication headers, endpoint should deny access
        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}")
        self.assertEqual(resp.status_code, 401)

    @skip_auth_and_permissions(GET_PROJECT_VIEW_PATH)
    def test_missing_project_uuid_returns_400(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "project_uuid is required"})

    @skip_auth_and_permissions(GET_PROJECT_VIEW_PATH)
    def test_nonexistent_project_returns_404(self):
        random_proj = uuid.uuid4()
        resp = self.client.get(f"{self.url}?project_uuid={random_proj}")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    @skip_auth_and_permissions(GET_PROJECT_VIEW_PATH)
    def test_success_returns_project_data(self):
        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["project_uuid"], str(self.org.proj_uuid))
        self.assertEqual(data["name"], self.org.name)
        self.assertEqual(data["is_active"], self.org.is_active)
        self.assertEqual(data["brain_on"], self.org.brain_on)


@override_settings(ROOT_URLCONF="temba.api.v2.projects.urls")
class ProjectsUrlsTest(SimpleTestCase):
    def test_projects_url_resolves_to_get_project_view(self):
        url = reverse("projects")
        self.assertEqual(url, "/projects")
        match = resolve(url)
        self.assertEqual(getattr(match.func, "view_class", None), GetProjectView)

    def test_project_language_url_resolves_to_project_language_view(self):
        url = reverse("project_language")
        self.assertEqual(url, "/projects/project_language")
        match = resolve(url)
        self.assertEqual(getattr(match.func, "view_class", None), ProjectLanguageView)


class ProjectLanguageViewTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

        self.url = reverse("api.v2.project_language")

    def test_request_without_project_uuid_and_channel_uuid(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_request_with_channel_uuid(self):
        channel = self.create_channel("TG", "Test Channel", "test", org=self.org)
        response = self.client.get(f"{self.url}?channel_uuid={channel.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"language": self.org.language})

    def test_request_with_channel_uuid_notfound(self):
        url = f"{self.url}?channel_uuid=2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_request_with_project_uuid(self):
        response = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"language": self.org.language})

    def test_request_with_project_uuid_notfound(self):
        url = f"{self.url}?project_uuid=2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
