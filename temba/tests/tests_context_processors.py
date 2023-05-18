from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser

from temba.context_processors_weni import show_onboard_modal
from temba.tests import TembaTest
from temba.triggers.models import Trigger


class OnboardModalTest(TembaTest):
    def test_show_onboard_modal_no_user(self):
        request = MagicMock()
        request.user = None

        result = show_onboard_modal(request)
        self.assertFalse(result["show_trigger_onboard_modal"])

    def test_show_onboard_modal_anonymous(self):
        request = MagicMock()
        request.user = AnonymousUser()

        result = show_onboard_modal(request)
        self.assertFalse(result["show_trigger_onboard_modal"])

    def test_show_onboard_modal_with_triggers(self):
        request = MagicMock()
        request.user = self.user

        flow = self.create_flow()
        Trigger.objects.create(org=self.org, flow=flow, keyword="key", created_by=self.user, modified_by=self.user)

        result = show_onboard_modal(request)
        self.assertFalse(result["show_trigger_onboard_modal"])

    def test_show_onboard_modal_no_triggers(self):
        request = MagicMock()
        request.user = self.user

        result = show_onboard_modal(request)
        self.assertTrue(result["show_trigger_onboard_modal"])
