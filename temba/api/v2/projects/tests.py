import uuid
from functools import wraps
from unittest.mock import patch

from rest_framework.authentication import BasicAuthentication

from django.urls import reverse

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
