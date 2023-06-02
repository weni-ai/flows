from django.contrib.auth.models import User
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, TestCase
from django.test.client import RequestFactory

from temba.externals.models import ExternalService
from temba.externals.types.omie.type import OmieType
from temba.externals.types.omie.views import ConnectView
from temba.orgs.models import Org


class ConnectViewTestCase(TestCase):
    databases = ("default", "readonly")

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="testpassword")
        self.org = Org.objects.create(
            name="X-Temba-Org",
            timezone="Africa/Kigali",
            created_by=self.user,
            modified_by=self.user,
        )

    def get_request(self, data=None):
        request = self.factory.post("/connect/", data=data)
        request.user = self.user

        # Add necessary middlewares to the request object
        middleware = SessionMiddleware()
        middleware.process_request(request)
        middleware = MessageMiddleware()
        middleware.process_request(request)

        # Configure message storage
        """messages = FallbackStorage(request)
        setattr(request, '_messages', messages)"""

        return request

    def test_form_valid(self):
        request = self.get_request(
            data={
                "name": "Omie",
                "app_key": "your-app-key",
                "app_secret": "your-app-secret",
            }
        )

        view = ConnectView(OmieType())
        view.setup(request)
        view.org = self.org

        response = view.post(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/org/home/")

        external_service = ExternalService.objects.filter(name="Omie").first()
        self.assertIsNotNone(external_service)
        self.assertEqual(external_service.external_service_type, OmieType.slug)
        self.assertEqual(external_service.config[OmieType.CONFIG_APP_KEY], "your-app-key")
        self.assertEqual(external_service.config[OmieType.CONFIG_APP_SECRET], "your-app-secret")
        self.assertEqual(external_service.created_by, self.user)
        self.assertEqual(external_service.modified_by, self.user)

    def test_form_invalid(self):
        client = Client()
        request = self.get_request(data={})

        view = ConnectView(OmieType())
        view.setup(request)
        view.org = self.org

        response = client.post("/connect/", data=request.POST)
        self.assertEqual(response.status_code, 404)

        external_service = ExternalService.objects.filter(name="Omie").first()
        self.assertIsNone(external_service)

    def test_invalid_app_key_2(self):
        request = self.factory.get("/")
        form = ConnectView.Form(request=request, data={"app_key": 2}, external_service_type="omie")
        form.is_valid()

        self.assertFalse(form.is_valid())

    def test_invalid_app_key_3(self):
        request = self.factory.get("/")
        form = ConnectView.Form(request=request, data={}, external_service_type="omie")
        form.is_valid()

        self.assertFalse(form.is_valid())
