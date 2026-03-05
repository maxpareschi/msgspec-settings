"""Mapping merge and collection utility helpers."""

from collections.abc import Mapping, MutableMapping
from typing import Any


def deep_merge_into(
    destination: MutableMapping[str, Any],
    update: Mapping[str, Any],
) -> None:
    """Recursively merge ``update`` into ``destination`` in place.

    Args:
        destination: Mutable mapping mutated in place.
        update: Mapping patch to apply.

    Returns:
        ``None``.
    """
    for key, value in update.items():
        if isinstance(value, Mapping):
            existing = destination.get(key)
            if isinstance(existing, MutableMapping):
                deep_merge_into(existing, value)
                continue
        destination[key] = value


def set_nested(data: MutableMapping[str, Any], dotted_key: str, value: Any) -> None:
    """Set a value at a dotted path inside a nested mapping.

    Args:
        data: Target mapping.
        dotted_key: Path such as ``log.level``.
        value: Value to assign.

    Returns:
        ``None``.

    Raises:
        TypeError: If an intermediate element is not a mapping.
    """
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        existing = data.get(part)
        if existing is None:
            child: MutableMapping[str, Any] = {}
            data[part] = child
            data = child
            continue
        if not isinstance(existing, MutableMapping):
            raise TypeError(
                f"Cannot set nested key '{dotted_key}': '{part}' maps to "
                f"{type(existing).__name__}, expected mapping"
            )
        data = existing
    data[parts[-1]] = value


def dedupe_keep_order(values: list[str]) -> list[str]:
    """Return values with duplicates removed, preserving order.

    Args:
        values: Input values.

    Returns:
        Deduplicated list preserving first occurrence order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
