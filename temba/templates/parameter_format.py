import re

PARAMETER_FORMAT_POSITIONAL = "positional"
PARAMETER_FORMAT_NAMED = "named"

NAMED_TEMPLATE_CHANNEL_TYPES = {"WAC", "WCD"}

PLACEHOLDER_RE = re.compile(r"{{([^{}]+)}}")
NAMED_PARAM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OPTIONAL_FILLER = " "


def normalize_parameter_format(value):
    if isinstance(value, str) and value.strip().lower() == PARAMETER_FORMAT_NAMED:
        return PARAMETER_FORMAT_NAMED
    return PARAMETER_FORMAT_POSITIONAL


def is_named_format(value):
    return normalize_parameter_format(value) == PARAMETER_FORMAT_NAMED


def _is_named_param(name):
    return bool(name) and not name.isdigit() and bool(NAMED_PARAM_RE.match(name))


def extract_parameter_names(text):
    names = []
    seen = set()
    for raw in PLACEHOLDER_RE.findall(text or ""):
        name = raw.strip()
        if not _is_named_param(name) or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names


def _example_parameter_names(named_examples):
    names = []
    seen = set()
    for item in named_examples or []:
        raw = (item or {}).get("param_name")
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not _is_named_param(name) or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names


def extract_parameter_names_from_components(components):
    names = []
    seen = set()
    for component in components or []:
        if (component.get("type") or "").upper() != "BODY":
            continue
        body_names = extract_parameter_names(component.get("text"))
        example_names = _example_parameter_names((component.get("example") or {}).get("body_text_named_params"))
        # Body placeholders are authoritative (order and membership). Examples fill in
        # only when the body has no named placeholders, so we never record example-only names.
        for name in body_names or example_names:
            if name not in seen:
                names.append(name)
                seen.add(name)
    return names


def has_placeholders(text):
    return bool(PLACEHOLDER_RE.search(text or ""))


def is_provided_value(value):
    return value is not None and str(value).strip() != ""
