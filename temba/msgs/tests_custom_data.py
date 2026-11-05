import json
from unittest import TestCase

from temba.msgs.custom_data import (
    CUSTOM_DATA_ERR_FORBIDDEN_KEY,
    CUSTOM_DATA_ERR_NOT_OBJECT,
    CUSTOM_DATA_ERR_TOO_DEEP,
    CUSTOM_DATA_ERR_TOO_LARGE,
    CUSTOM_DATA_MAX_DEPTH,
    CUSTOM_DATA_MAX_SERIALIZED_BYTES,
    normalize_custom_data_in_msg,
    validate_custom_data,
)


def _nested_object(depth):
    root = {}
    current = root
    for _ in range(depth - 1):
        current["x"] = {}
        current = current["x"]
    return root


def _nested_list_chain(list_depth):
    inner = []
    current = inner
    for _ in range(list_depth - 1):
        nested = []
        current.append(nested)
        current = nested
    return {"items": inner}


class CustomDataValidationTest(TestCase):
    def test_null_and_non_object(self):
        for value in (None, "x", [], 1, True):
            with self.assertRaises(ValueError) as ctx:
                validate_custom_data(value)
            self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_NOT_OBJECT)

    def test_empty_object_is_valid(self):
        validate_custom_data({})

    def test_normalize_empty_object_is_absence(self):
        msg = {"text": "hi", "custom_data": {}}
        normalized = normalize_custom_data_in_msg(msg)
        self.assertNotIn("custom_data", normalized)
        self.assertEqual(msg["custom_data"], {})

    def test_normalize_omitted_key(self):
        msg = {"text": "hi"}
        self.assertIs(normalize_custom_data_in_msg(msg), msg)

    def test_normalize_non_empty_custom_data_unchanged(self):
        msg = {"text": "hi", "custom_data": {"order_id": "1"}}
        self.assertIs(normalize_custom_data_in_msg(msg), msg)
        self.assertEqual(msg["custom_data"], {"order_id": "1"})

    def test_non_string_dict_keys_coerced(self):
        validate_custom_data({1: "ok", 2: ["a"]})

    def test_list_nesting_depth_limit(self):
        # Deepest list is entered at depth list_depth + 1 (root dict is depth 1).
        validate_custom_data(_nested_list_chain(CUSTOM_DATA_MAX_DEPTH - 1))
        with self.assertRaises(ValueError) as ctx:
            validate_custom_data(_nested_list_chain(CUSTOM_DATA_MAX_DEPTH))
        self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_TOO_DEEP)

    def test_depth_32_accepted_33_rejected(self):
        validate_custom_data(_nested_object(CUSTOM_DATA_MAX_DEPTH))
        with self.assertRaises(ValueError) as ctx:
            validate_custom_data(_nested_object(CUSTOM_DATA_MAX_DEPTH + 1))
        self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_TOO_DEEP)

    def test_forbidden_keys_nested_and_in_array(self):
        with self.assertRaises(ValueError) as ctx:
            validate_custom_data({"$x": 1})
        self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_FORBIDDEN_KEY)

        with self.assertRaises(ValueError) as ctx:
            validate_custom_data({"outer": {"a.b": 1}})
        self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_FORBIDDEN_KEY)

        with self.assertRaises(ValueError) as ctx:
            validate_custom_data({"items": [{"bad.key": True}]})
        self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_FORBIDDEN_KEY)

    def test_lone_surrogate_rejected_with_contract_message(self):
        with self.assertRaises(ValueError) as ctx:
            validate_custom_data({"a": "\ud800"})
        self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_NOT_OBJECT)

    def test_serialized_byte_boundary(self):
        base_size = len(json.dumps({"a": ""}, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        exact_payload = "x" * (CUSTOM_DATA_MAX_SERIALIZED_BYTES - base_size)
        exact = {"a": exact_payload}
        self.assertEqual(
            len(json.dumps(exact, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
            CUSTOM_DATA_MAX_SERIALIZED_BYTES,
        )
        validate_custom_data(exact)

        too_big = {"a": exact_payload + "y"}
        with self.assertRaises(ValueError) as ctx:
            validate_custom_data(too_big)
        self.assertEqual(str(ctx.exception), CUSTOM_DATA_ERR_TOO_LARGE)
