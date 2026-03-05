"""Tests for trimmed helper functions module."""

from typing import Annotated, Literal

import msgspec
import pytest
from msgspec import Meta

from msgspec_settings.mapping import (
    flatten_model_fields_with_alias,
    map_env_to_model,
    split_mapping_by_model_fields,
)
from msgspec_settings.merge import dedupe_keep_order, deep_merge_into, set_nested
from msgspec_settings.typing import (
    _COERCE_FAILED,
    coerce_env_value,
    get_struct_subtype,
    try_json_decode,
    unwrap_annotated,
)

from ._models import LogModel, ServerModel, SimpleModel


def test_flatten_model_fields_with_alias_returns_leaf_paths() -> None:
    """Flatten helper should return canonical and alias paths for leaf fields."""

    class AliasModel(msgspec.Struct, kw_only=True):
        port: int = msgspec.field(default=8080, name="PORT")

    result = flatten_model_fields_with_alias(AliasModel)
    assert result["port"][0] == "PORT"
    assert result["port"][1] is int


def test_set_nested_conflict_raises() -> None:
    """set_nested should fail if intermediate path points to non-mapping."""
    data = {"log": "oops"}
    with pytest.raises(TypeError, match="Cannot set nested key"):
        set_nested(data, "log.level", "INFO")


def test_deep_merge_into_merges_nested_mappings() -> None:
    """deep_merge_into should recursively merge nested mapping keys."""
    destination = {"a": {"b": 1}, "x": 1}
    deep_merge_into(destination, {"a": {"c": 2}, "x": 2})
    assert destination == {"a": {"b": 1, "c": 2}, "x": 2}


def test_get_struct_subtype_supports_optional_and_annotated() -> None:
    """Struct subtype extraction should support Optional and Annotated wrappers."""
    assert get_struct_subtype(LogModel) is LogModel
    assert get_struct_subtype(LogModel | None) is LogModel

    annotated = Annotated[LogModel | None, Meta(description="optional")]
    assert get_struct_subtype(annotated) is LogModel


def test_coerce_env_value_for_primitives_union_and_literal() -> None:
    """coerce_env_value should support primitives, union, optional, and literal."""
    assert coerce_env_value("123", int) == 123
    assert coerce_env_value("true", bool) is True
    assert coerce_env_value("abc", str) == "abc"
    assert coerce_env_value("", int | None) is None
    assert coerce_env_value("123", int | str) == 123
    assert coerce_env_value("abc", int | str) == "abc"
    assert coerce_env_value("INFO", Literal["DEBUG", "INFO"]) == "INFO"


def test_map_env_to_model_nested_and_json_precedence() -> None:
    """map_env_to_model should resolve nested keys and enforce flat-over-json precedence."""
    first = {"LOG": '{"level":"DEBUG"}', "LOG_LEVEL": "WARN", "HOST": "example.com"}
    second = {"LOG_LEVEL": "WARN", "LOG": '{"level":"DEBUG"}', "HOST": "example.com"}

    first_data = map_env_to_model(first, ServerModel, "_")
    second_data = map_env_to_model(second, ServerModel, "_")

    assert first_data["host"] == "example.com"
    assert second_data["host"] == "example.com"
    assert first_data["log"]["level"] == "WARN"
    assert second_data["log"]["level"] == "WARN"


def test_map_env_to_model_custom_separator() -> None:
    """map_env_to_model should support custom nesting separators."""
    data = map_env_to_model({"LOG__LEVEL": "ERROR"}, ServerModel, "__")
    assert data["log"]["level"] == "ERROR"


def test_unwrap_annotated() -> None:
    """unwrap_annotated should recursively strip Annotated wrappers."""
    annotation = Annotated[Annotated[str, Meta(min_length=1)], Meta(max_length=64)]
    assert unwrap_annotated(annotation) is str


def test_dedupe_keep_order() -> None:
    """dedupe_keep_order should preserve first occurrence order."""
    assert dedupe_keep_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_flatten_with_nested_model() -> None:
    """Flatten helper should include nested canonical/alias paths."""
    result = flatten_model_fields_with_alias(ServerModel)
    assert result["host"] == ("host", str)
    assert result["log.level"] == ("log.level", str)


def test_try_json_decode_failure_returns_sentinel() -> None:
    """Invalid JSON should return the internal coercion-failed sentinel."""
    assert try_json_decode("not-json") is _COERCE_FAILED


def test_map_env_to_model_rejects_empty_separator() -> None:
    """Empty separator should raise ValueError."""
    with pytest.raises(ValueError, match="nested_separator must be a non-empty"):
        map_env_to_model({"HOST": "x"}, SimpleModel, "")


def test_map_env_to_model_can_collect_unmatched() -> None:
    """Optional unmatched collection should return unresolved env keys."""
    mapped, unmatched = map_env_to_model(
        {"HOST": "example.com", "HOTS": "typo"},
        SimpleModel,
        collect_unmatched=True,
    )
    assert mapped["host"] == "example.com"
    assert unmatched == {"HOTS": "typo"}


def test_split_mapping_by_model_fields_extracts_unknown_nested_keys() -> None:
    """Mapping split helper should separate known and unknown nested keys."""
    payload = {
        "host": "example.com",
        "extra": "x",
        "log": {"level": "DEBUG", "levle": "typo"},
    }
    mapped, unmapped = split_mapping_by_model_fields(payload, ServerModel)

    assert mapped == {"host": "example.com", "log": {"level": "DEBUG"}}
    assert unmapped == {"extra": "x", "log": {"levle": "typo"}}
