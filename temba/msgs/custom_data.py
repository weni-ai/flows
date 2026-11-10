import json

CUSTOM_DATA_MAX_SERIALIZED_BYTES = 16384
CUSTOM_DATA_MAX_DEPTH = 32

CUSTOM_DATA_ERR_NOT_OBJECT = "custom_data must be an object"
CUSTOM_DATA_ERR_TOO_LARGE = f"custom_data must be at most {CUSTOM_DATA_MAX_SERIALIZED_BYTES} bytes when serialized"
CUSTOM_DATA_ERR_TOO_DEEP = f"custom_data must have at most {CUSTOM_DATA_MAX_DEPTH} levels of nesting"
CUSTOM_DATA_ERR_FORBIDDEN_KEY = "custom_data keys must not start with '$' or contain '.'"


def validate_custom_data(value):
    if not isinstance(value, dict):
        raise ValueError(CUSTOM_DATA_ERR_NOT_OBJECT)

    _walk_custom_data(value, depth=1)

    try:
        serialized = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(CUSTOM_DATA_ERR_NOT_OBJECT)
    if len(serialized) > CUSTOM_DATA_MAX_SERIALIZED_BYTES:
        raise ValueError(CUSTOM_DATA_ERR_TOO_LARGE)


def normalize_custom_data_in_msg(msg: dict) -> dict:
    if "custom_data" not in msg:
        return msg
    if msg["custom_data"] == {}:
        msg = dict(msg)
        del msg["custom_data"]
    return msg


def _walk_custom_data(value, depth):
    if isinstance(value, dict):
        if depth > CUSTOM_DATA_MAX_DEPTH:
            raise ValueError(CUSTOM_DATA_ERR_TOO_DEEP)
        for key, child in value.items():
            if not isinstance(key, str):
                key = str(key)
            if key.startswith("$") or "." in key:
                raise ValueError(CUSTOM_DATA_ERR_FORBIDDEN_KEY)
            _walk_custom_data(child, depth + 1)
    elif isinstance(value, list):
        if depth > CUSTOM_DATA_MAX_DEPTH:
            raise ValueError(CUSTOM_DATA_ERR_TOO_DEEP)
        for child in value:
            _walk_custom_data(child, depth + 1)
