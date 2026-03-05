"""Mapping helpers for field resolution and source payload splitting."""

from collections.abc import Mapping
from typing import Any

from msgspec import Struct
from msgspec.structs import fields as struct_fields

from .merge import set_nested
from .typing import (
    _COERCE_FAILED,
    coerce_env_value,
    get_struct_subtype,
    try_json_decode,
)


def _normalize_token(value: str) -> str:
    """Normalize one lookup token used for key matching.

    Args:
        value: Raw token from environment or alias input.

    Returns:
        Lowercased token with common separators normalized to ``_``.
    """
    normalized = (
        value.strip().lower().replace("-", "_").replace(".", "_").replace(" ", "_")
    )
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _field_names(field_info: Any) -> tuple[str, str]:
    """Return canonical and encoded names for one ``msgspec`` field.

    Args:
        field_info: Field metadata from ``msgspec.structs.fields``.

    Returns:
        Tuple ``(canonical_name, encoded_name)``.
    """
    canonical = field_info.name
    encoded = getattr(field_info, "encode_name", None)
    if not isinstance(encoded, str) or not encoded:
        encoded = canonical
    return canonical, encoded


def split_mapping_by_model_fields(
    payload: Mapping[str, Any],
    model: type[Struct],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a mapping into model-recognized keys and unmapped keys.

    Recognition supports canonical and encoded/aliased field names. Nested
    mappings recurse only for nested ``Struct`` fields.

    Args:
        payload: Input mapping to split.
        model: Target model used to recognize valid keys.

    Returns:
        Tuple ``(mapped, unmapped)`` where ``mapped`` can be safely passed to
        ``msgspec.convert(..., type=model)``.
    """
    field_lookup: dict[str, type[Struct] | None] = {}

    for field_info in struct_fields(model):
        canonical_name, alias_name = _field_names(field_info)
        nested = get_struct_subtype(field_info.type)
        field_lookup[canonical_name] = nested
        field_lookup[alias_name] = nested

    mapped: dict[str, Any] = {}
    unmapped: dict[str, Any] = {}

    for raw_key, value in payload.items():
        key = raw_key if isinstance(raw_key, str) else str(raw_key)
        if key not in field_lookup:
            unmapped[key] = value
            continue
        nested_model = field_lookup[key]

        if nested_model is not None and isinstance(value, Mapping):
            child_mapped, child_unmapped = split_mapping_by_model_fields(
                value,
                nested_model,
            )
            mapped[key] = child_mapped
            if child_unmapped:
                unmapped[key] = child_unmapped
            continue

        mapped[key] = value

    return mapped, unmapped


def flatten_model_fields_with_alias(
    model: type,
    prefix: str = "",
    separator: str = ".",
) -> dict[str, tuple[str, Any]]:
    """Flatten leaf model fields to canonical-path metadata.

    Args:
        model: Root model to inspect.
        prefix: Optional traversal prefix.
        separator: Path separator.

    Returns:
        Mapping ``canonical_path -> (alias_path, field_type)`` for leaf fields.
    """
    result: dict[str, tuple[str, Any]] = {}

    def _walk(current_model: type, canonical_prefix: str, alias_prefix: str) -> None:
        for field_info in struct_fields(current_model):
            canonical_name, alias_name = _field_names(field_info)
            canonical_path = (
                f"{canonical_prefix}{separator}{canonical_name}"
                if canonical_prefix
                else canonical_name
            )
            alias_path = (
                f"{alias_prefix}{separator}{alias_name}" if alias_prefix else alias_name
            )

            nested = get_struct_subtype(field_info.type)
            if nested is not None:
                _walk(nested, canonical_path, alias_path)
                continue
            result[canonical_path] = (alias_path, field_info.type)

    _walk(model, prefix, prefix)
    return result


def _lookup_field_by_token(
    model: type,
    token: str,
) -> tuple[str, Any, type[Struct] | None] | None:
    """Resolve one token against direct fields on ``model``.

    Args:
        model: Model to inspect.
        token: Candidate field token.

    Returns:
        Tuple ``(canonical_name, field_type, nested_struct_type)`` when a field
        matches, otherwise ``None``.
    """
    normalized = _normalize_token(token)
    for field_info in struct_fields(model):
        canonical_name, alias_name = _field_names(field_info)
        if normalized not in {
            _normalize_token(canonical_name),
            _normalize_token(alias_name),
        }:
            continue
        return canonical_name, field_info.type, get_struct_subtype(field_info.type)
    return None


def _resolve_segments(model: type, segments: list[str]) -> tuple[str, Any] | None:
    """Resolve explicit key segments to a canonical dotted field path.

    Args:
        model: Root model to traverse.
        segments: Pre-split key segments.

    Returns:
        Tuple ``(canonical_path, field_type)`` on success, otherwise ``None``.
    """
    current_model = model
    canonical_parts: list[str] = []

    for index, segment in enumerate(segments):
        resolved = _lookup_field_by_token(current_model, segment)
        if resolved is None:
            return None

        canonical_name, field_type, nested = resolved
        canonical_parts.append(canonical_name)

        if index == len(segments) - 1:
            return ".".join(canonical_parts), field_type
        if nested is None:
            return None
        current_model = nested

    return None


def _match_env_parts_underscore(
    parts: list[str],
    model: type,
    prefix: str = "",
) -> tuple[str, Any] | None:
    """Resolve underscore-delimited key parts using greedy matching.

    Args:
        parts: Key tokens split on ``_``.
        model: Model used for path resolution.
        prefix: Current canonical dotted prefix during recursion.

    Returns:
        Tuple ``(canonical_path, field_type)`` on success, otherwise ``None``.
    """
    for i in range(1, len(parts) + 1):
        token = "_".join(parts[:i])
        resolved = _lookup_field_by_token(model, token)
        if resolved is None:
            continue

        canonical_name, field_type, nested = resolved
        full_path = f"{prefix}.{canonical_name}" if prefix else canonical_name
        remaining = parts[i:]

        if not remaining:
            return full_path, field_type

        if nested is None:
            continue

        nested_result = _match_env_parts_underscore(remaining, nested, prefix=full_path)
        if nested_result is not None:
            return nested_result

    return None


def map_env_to_model(
    filtered: dict[str, str],
    model: type,
    separator: str = "_",
    collect_unmatched: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, str]]:
    """Map filtered env-like key/value pairs to model-shaped nested data.

    Args:
        filtered: Uppercased env keys with prefix already removed.
        model: Target model type.
        separator: Nested key separator (for example ``"_"`` or ``"__"``).
        collect_unmatched: When true, also return unmatched key/value pairs.

    Returns:
        Nested dictionary suitable for ``msgspec.convert(..., type=model)``.
        When ``collect_unmatched`` is true, returns
        ``(mapped_data, unmatched_data)``.

    Raises:
        ValueError: If ``separator`` is empty.
    """
    if not isinstance(separator, str) or separator == "":
        raise ValueError("nested_separator must be a non-empty string")

    result: dict[str, Any] = {}
    unmatched: dict[str, str] = {}
    struct_patches: list[tuple[str, dict[str, Any]]] = []
    leaf_patches: list[tuple[str, Any]] = []

    for env_key, raw_value in filtered.items():
        dotted_path: str | None = None
        field_type: Any = None

        if separator == "_":
            parts = [part for part in env_key.upper().split("_") if part]
            matched = _match_env_parts_underscore(parts, model)
            if matched is not None:
                dotted_path, field_type = matched
        else:
            segments = [
                segment for segment in env_key.split(separator.upper()) if segment
            ]
            resolved = _resolve_segments(model, segments)
            if resolved is not None:
                dotted_path, field_type = resolved

        if dotted_path is None:
            if collect_unmatched:
                unmatched[env_key] = raw_value
            continue

        if get_struct_subtype(field_type) is not None:
            decoded = try_json_decode(raw_value)
            if decoded is not _COERCE_FAILED and isinstance(decoded, dict):
                struct_patches.append((dotted_path, decoded))
            elif collect_unmatched:
                unmatched[env_key] = raw_value
            continue

        coerced = coerce_env_value(raw_value, field_type)
        if coerced is not _COERCE_FAILED:
            leaf_patches.append((dotted_path, coerced))
        elif collect_unmatched:
            unmatched[env_key] = raw_value

    # Apply in two passes so explicit leaf keys always override JSON subkeys.
    for dotted_path, patch in struct_patches:
        set_nested(result, dotted_path, patch)
    for dotted_path, leaf in leaf_patches:
        set_nested(result, dotted_path, leaf)

    if collect_unmatched:
        return result, unmatched
    return result


__all__ = (
    "flatten_model_fields_with_alias",
    "map_env_to_model",
    "split_mapping_by_model_fields",
)
