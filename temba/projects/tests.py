from unittest.mock import Mock

from django.conf import settings
from django.test import TestCase, override_settings

from temba.projects.checks import project_events_legacy_actions
from temba.projects.consumers.project_events import EventAction
from temba.projects.usecases.exceptions import InvalidTemplateTypeData
from temba.projects.usecases.flow_setup_handler import FlowSetupHandlerUseCase


class ProjectEventsLegacyActionsCheckTest(TestCase):
    def test_default_lists_every_action(self):
        self.assertCountEqual(settings.PROJECT_EVENTS_LEGACY_ACTIONS, [action.value for action in EventAction])
        self.assertEqual(project_events_legacy_actions(None), [])

    @override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])
    def test_empty_list_is_valid(self):
        self.assertEqual(project_events_legacy_actions(None), [])

    @override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=["deleted", "bogus"])
    def test_unknown_action_is_an_error(self):
        errors = project_events_legacy_actions(None)

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "projects.E001")
        self.assertIn("bogus", errors[0].msg)
        self.assertNotIn("deleted", errors[0].msg)


class TestFlowSetupHandler(TestCase):
    def test_disable_flows_has_issues(self):
        project = Mock()
        sample_flows = {
            "flows": [
                {"name": "Flow1"},
                {"name": "Flow2"},
                {"name": "Flow3"},
            ]
        }
        project.flows.filter.return_value = project.flows

        handler = FlowSetupHandlerUseCase()
        handler.disable_flows_has_issues(project, sample_flows)

        expected_names = ["Flow1", "Flow2", "Flow3"]
        project.flows.filter.assert_called_once_with(name__in=expected_names)

        project.flows.update.assert_called_once_with(has_issues=False)

    def test_setup_flows_in_project_empty_setup(self):
        project = Mock()
        template_type = Mock()
        user = Mock()

        template_type.setup = {}

        handler = FlowSetupHandlerUseCase()
        with self.assertRaises(InvalidTemplateTypeData):
            handler.setup_flows_in_project(project, template_type, user)

    def test_setup_flows_in_project(self):
        project = Mock()
        template_type = Mock()
        user = Mock()

        setup = {"flows": [{"name": "Flow1"}, {"name": "Flow2"}]}
        template_type.setup = setup

        project.import_app = Mock()

        handler = FlowSetupHandlerUseCase()
        handler.setup_flows_in_project(project, template_type, user)

        project.import_app.assert_called_once_with(setup, user)
