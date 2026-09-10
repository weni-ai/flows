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


def extract_parameter_names(text):
    names = []
    seen = set()
    for raw in PLACEHOLDER_RE.findall(text or ""):
        name = raw.strip()
        if not name or name.isdigit() or not NAMED_PARAM_RE.match(name):
            continue
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names


def extract_parameter_names_from_components(components):
    names = []
    seen = set()
    for component in components or []:
        if (component.get("type") or "").upper() != "BODY":
            continue
        example = component.get("example") or {}
        named_examples = example.get("body_text_named_params") or []
        if named_examples:
            for item in named_examples:
                name = (item or {}).get("param_name")
                if name and name not in seen:
                    names.append(name)
                    seen.add(name)
        for name in extract_parameter_names(component.get("text")):
            if name not in seen:
                names.append(name)
                seen.add(name)
    return names


def has_placeholders(text):
    return bool(PLACEHOLDER_RE.search(text or ""))


def is_provided_value(value):
    return value is not None and str(value).strip() != ""
