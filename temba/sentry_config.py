import builtins
import os

try:
    from redis.exceptions import LockNotOwnedError
except ImportError:  # pragma: no cover
    LockNotOwnedError = None

# Project/third-party exceptions that can be referenced by name in SENTRY_IGNORE_ERRORS
CUSTOM_EXCEPTIONS = {}
if LockNotOwnedError is not None:
    CUSTOM_EXCEPTIONS["LockNotOwnedError"] = LockNotOwnedError


def get_float_env(var_name: str, default: float) -> float:
    """Read an environment variable and convert it to float safely."""
    value = os.getenv(var_name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def get_ignored_errors_from_env(env_var: str = "SENTRY_IGNORE_ERRORS"):
    """
    Resolve exception classes from a comma-separated env var.

    Supports builtin exceptions (e.g. ValueError) and names registered in
    CUSTOM_EXCEPTIONS (e.g. LockNotOwnedError).
    """
    raw_env = os.getenv(env_var, "")
    if not raw_env:
        return []

    ignored_classes = []
    error_names = [name.strip() for name in raw_env.split(",") if name.strip()]

    for name in error_names:
        err_cls = getattr(builtins, name, None)
        if err_cls is None:
            err_cls = CUSTOM_EXCEPTIONS.get(name)

        if err_cls and isinstance(err_cls, type) and issubclass(err_cls, BaseException):
            ignored_classes.append(err_cls)

    return ignored_classes
