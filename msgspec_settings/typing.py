"""Type-introspection and scalar coercion helpers."""

from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from msgspec import Struct, convert
from msgspec.json import decode as json_decode

_COERCE_FAILED = object()


def unwrap_annotated(target_type: Any) -> Any:
    """Recursively unwrap ``typing.Annotated`` annotations.

    Args:
        target_type: Annotation to inspect.

    Returns:
        The first non-``Annotated`` wrapped annotation.
    """
    origin = get_origin(target_type)
    if origin is Annotated:
        args = get_args(target_type)
        if args:
            return unwrap_annotated(args[0])
    return target_type


def get_struct_subtype(target_type: Any) -> type[Struct] | None:
    """Extract a concrete ``Struct`` subtype from an annotation.

    Supports direct ``Struct`` subclasses and optional wrappers such as
    ``MyStruct | None``.

    Args:
        target_type: Annotation to inspect.

    Returns:
        A concrete ``Struct`` subtype, or ``None`` when not applicable.
    """
    target_type = unwrap_annotated(target_type)
    if (
        isinstance(target_type, type)
        and issubclass(target_type, Struct)
        and target_type is not Struct
    ):
        return target_type

    origin = get_origin(target_type)
    if origin is None:
        return None

    args = get_args(target_type)
    non_none = [arg for arg in args if arg is not type(None)]
    if len(non_none) != 1:
        return None
    return get_struct_subtype(non_none[0])


def try_json_decode(value: str) -> Any:
    """Attempt to decode a JSON string.

    Args:
        value: Raw JSON candidate.

    Returns:
        Decoded value, or ``_COERCE_FAILED`` on parse errors.
    """
    try:
        return json_decode(value.encode())
    except Exception:
        return _COERCE_FAILED


def _is_union_origin(origin: Any) -> bool:
    """Return whether ``origin`` represents a union annotation."""
    return origin in (Union, UnionType)


def _coerce_literal_member(value: str, literal_value: Any) -> Any:
    """Coerce one raw string against one literal member value."""
    if literal_value is None:
        if value.strip() == "":
            return None
        return _COERCE_FAILED

    literal_type = type(literal_value)
    if literal_type is bool:
        return coerce_env_value(value, bool)
    if literal_type is int:
        return coerce_env_value(value, int)
    if literal_type is float:
        return coerce_env_value(value, float)
    if literal_type is str:
        return value

    try:
        return convert(value, literal_type)
    except Exception:
        return _COERCE_FAILED


def _coerce_literal_value(value: str, literal_type: Any) -> Any:
    """Coerce a string to one valid value of a ``Literal[...]`` annotation."""
    for literal_member in get_args(literal_type):
        coerced = _coerce_literal_member(value, literal_member)
        if coerced is _COERCE_FAILED:
            continue
        if literal_member is None:
            if coerced is None:
                return None
            continue
        if type(coerced) is type(literal_member) and coerced == literal_member:
            return literal_member
    return _COERCE_FAILED


def coerce_env_value(value: str, target_type: Any) -> Any:
    """Coerce an environment/CLI string to a target annotation.

    Supports primitive scalar targets, ``Literal[...]``, unions/optionals,
    and JSON-backed collection annotations.

    Args:
        value: Raw string value.
        target_type: Destination annotation.

    Returns:
        Coerced value, or ``_COERCE_FAILED`` when coercion fails.
    """
    target_type = unwrap_annotated(target_type)

    if target_type is str:
        return value

    if target_type is bool:
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off", ""):
            return False
        return _COERCE_FAILED

    if target_type is int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return _COERCE_FAILED

    if target_type is float:
        try:
            return float(value)
        except (ValueError, TypeError):
            return _COERCE_FAILED

    origin = get_origin(target_type)
    if origin is Literal:
        return _coerce_literal_value(value, target_type)

    if _is_union_origin(origin):
        args = get_args(target_type)
        non_none = [arg for arg in args if arg is not type(None)]
        has_none = len(non_none) != len(args)

        if has_none and len(non_none) == 1:
            if value.strip() == "":
                return None
            return coerce_env_value(value, non_none[0])

        for union_type in non_none:
            coerced = coerce_env_value(value, union_type)
            if coerced is not _COERCE_FAILED:
                return coerced

        if has_none and value.strip() == "":
            return None
        return _COERCE_FAILED

    if origin in (list, dict, tuple, set, frozenset):
        decoded = try_json_decode(value)
        if decoded is _COERCE_FAILED:
            return _COERCE_FAILED
        try:
            return convert(decoded, target_type)
        except Exception:
            return _COERCE_FAILED

    try:
        return convert(value, target_type)
    except Exception:
        return _COERCE_FAILED


__all__ = (
    "_COERCE_FAILED",
    "coerce_env_value",
    "get_struct_subtype",
    "try_json_decode",
    "unwrap_annotated",
)
