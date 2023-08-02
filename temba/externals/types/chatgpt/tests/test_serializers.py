from django.contrib.auth.models import User
from django.test import TestCase

from temba.externals.models import ExternalService
from temba.externals.types.chatgpt.serializers import ChatGPTSerializer
from temba.externals.types.chatgpt.type import ChatGPTType
from temba.orgs.models import Org


class ChatGPTSerializerTestCase(TestCase):
    def test_create(self):
        user = User.objects.create_user(username="super", email="super@user.com", password="super")
        org = Org.objects.create(
            name="X-Temba-Org",
            timezone="Africa/Kigali",
            created_by=user,
            modified_by=user,
        )

        type_ = ChatGPTType
        data = {
            "name": "ChatGPT",
            "api_key": "your-api-key",
            "ai_model": "gpt-3.5-turbo",
        }

        serializer = ChatGPTSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(type=type_, created_by=user, modified_by=user, org=org)

        self.assertIsInstance(instance, ExternalService)
        self.assertEqual(instance.name, "ChatGPT")
        self.assertEqual(instance.external_service_type, type_.slug)
        self.assertEqual(instance.config[type_.CONFIG_API_KEY], "your-api-key")
