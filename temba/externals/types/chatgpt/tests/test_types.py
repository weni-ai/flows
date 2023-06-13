import uuid

from django.contrib.auth.models import User
from django.test import TestCase

from temba.externals.models import ExternalService, Prompt
from temba.externals.types.chatgpt.type import ChatGPTType
from temba.orgs.models import Org

action_file = "temba/externals/types/chatgpt/actions.json"


class TestGetActions(TestCase):
    def setUp(self):
        self.file = open(action_file, encoding="utf-8")
        self.action = self.file.read()
        self.user = User.objects.create_user(username="super", email="super@user.com", password="super")
        self.org = Org.objects.create(
            name="Temba", timezone="Africa/Kigali", created_by=self.user, modified_by=self.user
        )
        self.external_service = ExternalService.objects.create(
            uuid=uuid.uuid4(),
            external_service_type="chatgpt",
            name="test_chatgpt",
            config={},
            org=self.org,
            created_by=self.user,
            modified_by=self.user,
        )

    def test_get_actions_no_prompt(self):
        actions = self.external_service.actions

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["name"], "ConsultarChatGPT")
        self.assertEqual(actions[0]["params"][0]["options"], [])

    def test_get_actions_with_prompt(self):
        prompt = Prompt.objects.create(
            text="Example Text",
            chat_gpt_service=self.external_service,
            created_by=self.user,
            modified_by=self.user,
        )

        actions = self.external_service.actions

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["name"], "ConsultarChatGPT")
        expected_options = {
            "text": prompt.text,
            "chat_gpt_service": self.external_service.id,
        }

        self.assertEqual(actions[0]["params"][0]["options"][0]["text"], expected_options["text"])
        self.assertEqual(
            actions[0]["params"][0]["options"][0]["chat_gpt_service_id"], expected_options["chat_gpt_service"]
        )

    def test_is_available_to(self):
        chatgpt_type = ChatGPTType()
        user = self.user

        result = chatgpt_type.is_available_to(user)

        self.assertTrue(result)
