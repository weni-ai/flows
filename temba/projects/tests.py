from unittest.mock import Mock

from django.test import TestCase

from temba.projects.usecases.exceptions import InvalidTemplateTypeData
from temba.projects.usecases.flow_setup_handler import FlowSetupHandlerUseCase


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
