import uuid

from temba.features.usecases.feature_template_integration import format_new_flows_data
from temba.flows.models import Flow
from temba.tests.base import TembaTest


class TestFormatNewFlowsData(TembaTest):
    def test_format_new_flows_data_empty(self):
        result = format_new_flows_data([])
        self.assertEqual(result, [])

    def test_format_new_flows_data_single_flow(self):
        flow = Flow.create(self.org, self.admin, Flow.get_unique_name(self.org, "Test flow"), base_language="base")
        flow.father_uuid = uuid.uuid4()
        result = format_new_flows_data([flow])
        expected = [{"base_uuid": flow.father_uuid, "uuid": flow.uuid, "name": "Test flow"}]
        self.assertEqual(result, expected)

    def test_format_new_flows_data_multiple_flows(self):
        flow1 = Flow.create(self.org, self.admin, Flow.get_unique_name(self.org, "Test flow 2"), base_language="base")
        flow2 = Flow.create(self.org, self.admin, Flow.get_unique_name(self.org, "Test flow 3"), base_language="base")
        flow1.father_uuid = uuid.uuid4()
        flow2.father_uuid = uuid.uuid4()
        result = format_new_flows_data([flow1, flow2])
        expected = [
            {"base_uuid": flow1.father_uuid, "uuid": flow1.uuid, "name": "Test flow 2"},
            {"base_uuid": flow2.father_uuid, "uuid": flow2.uuid, "name": "Test flow 3"},
        ]
        self.assertEqual(result, expected)
