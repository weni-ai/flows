from django.contrib.auth.models import User
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, TestCase
from django.test.client import RequestFactory

from temba.externals.models import ExternalService
from temba.externals.types.chatgpt.type import ChatGPTType
from temba.externals.types.chatgpt.views import ConnectView
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

        return request

    def test_form_valid(self):
        request = self.get_request(
            data={
                "service_name": "ChatGPT",
                "api_key": "your-api-key",
                "ai_model": "gpt-3.5-turbo",
            }
        )

        view = ConnectView(ChatGPTType())
        view.setup(request)
        view.org = self.org

        response = view.post(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/org/home/")

        external_service = ExternalService.objects.filter(name="ChatGPT").first()
        self.assertIsNotNone(external_service)
        self.assertEqual(external_service.external_service_type, ChatGPTType.slug)
        self.assertEqual(external_service.config[ChatGPTType.CONFIG_API_KEY], "your-api-key")
        self.assertEqual(external_service.created_by, self.user)
        self.assertEqual(external_service.modified_by, self.user)

    def test_form_invalid(self):
        client = Client()
        request = self.get_request(data={})

        view = ConnectView(ChatGPTType())
        view.setup(request)
        view.org = self.org

        response = client.post("/connect/", data=request.POST)
        self.assertEqual(response.status_code, 404)

        external_service = ExternalService.objects.filter(name="ChatGPT").first()
        self.assertIsNone(external_service)

    def test_invalid_app_secret(self):
        request = self.factory.get("/")
        form = ConnectView.Form(request=request, data={"app_key": 2}, external_service_type="chatgpt")
        form.is_valid()

        self.assertFalse(form.is_valid())

    def test_invalid_app_key(self):
        request = self.factory.get("/")
        form = ConnectView.Form(request=request, data={}, external_service_type="chatgpt")
        form.is_valid()

        self.assertFalse(form.is_valid())
