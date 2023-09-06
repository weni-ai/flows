import json

from django.test import TestCase

from temba.tickets.usecases.ticketer_creation import list_flow_definition_ticketers


class TicketerCreationTestCase(TestCase):
    def test_list_flow_definition_ticketers_return_flow_ticketers(self):
        ticketer_list = [
            {
                "uuid": "a69844ab-b49f-4988-9e13-2d2a50ffb23f",
                "name": "Setor teste EDA",
                "topic": {
                    "name": "opaaaaaaaaaaaaaaaaaa",
                    "uuid": "de6d19af-a905-475e-b824-bf7fbca277fd",
                },
            },
            {
                "uuid": "a69844ab-b49f-4988-9e13-2d2a50ffb23f",
                "name": "Setor teste EDA",
                "topic": {
                    "name": "Fila gg",
                    "uuid": "cb3ee8dc-705c-4512-893f-8d1d347680bb",
                },
            },
        ]

        with open("temba/tickets/usecases/tests/flowrevision_definition.json", "r") as file:
            definition = json.loads(file.read())

        ticketers = list_flow_definition_ticketers(definition)

        self.assertEquals(len(ticketers), 2)
        self.assertEquals(ticketer_list, ticketers)
