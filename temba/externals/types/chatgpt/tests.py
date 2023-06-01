from unittest.mock import patch

from django.urls import reverse

from temba.tests import MockResponse
from temba.tests.base import TembaTest
from temba.externals.models import ExternalService

from .type import ChatGPTType

class ChatGPTTypeTest(TembaTest):
    def test_is_available_to(self):
        self.assertTrue(ChatGPTType().is_available_to(self.admin))
    
class ChatGPTMixin(TembaTest):
    def setUp(self):
        super().setUp()
        self.connect_url = reverse("externals.types.chatgpt.connect")

class ChatGPTViewTest(ChatGPTMixin):
    def test_connect(self):
        self.client.force_login(self.admin)
        data = {
            "service_name": "chatgpt_test",
            "api_key": "API_KEY_123",
            "rules": "",
            "knowledge_base": "",
            "ai_model": "gpt-4",
        }
        
        with patch("requests.get") as mock_get:
            mock_get.return_value = MockResponse(200, "{}")
            response = self.client.post(self.connect_url, data=data)
            self.assertEqual(response.status_code, 302)

            exts = ExternalService.objects.order_by("id").last()
            self.assertEqual(data["service_name"], exts.name)
