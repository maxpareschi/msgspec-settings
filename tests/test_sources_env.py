"""Tests for environment datasource behavior."""

import pytest

from msgspec_settings import EnvironSource
from msgspec_settings.mapping import map_env_to_model

from ._models import (
    BoolLiteralModel,
    IntLiteralModel,
    LiteralModel,
    OptionalNestedModel,
    ServerModel,
    SimpleModel,
    UnionModel,
)


def test_simple_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prefix-filtered env vars should map to typed fields."""
    monkeypatch.setenv("APP_HOST", "envhost")
    monkeypatch.setenv("APP_PORT", "3000")
    src = EnvironSource(env_prefix="APP")
    data = src.load(model=SimpleModel)
    assert data["host"] == "envhost"
    assert data["port"] == 3000


def test_nested_env_vars_with_default_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Underscore nesting should resolve nested struct field paths."""
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("APP_LOG_FILE_PATH", "/tmp/app.log")
    src = EnvironSource(env_prefix="APP")
    data = src.load(model=ServerModel)
    assert data["log"]["level"] == "DEBUG"
    assert data["log"]["file_path"] == "/tmp/app.log"


def test_nested_env_vars_with_custom_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom separator should be honored for nested keys."""
    monkeypatch.setenv("APP_LOG__LEVEL", "WARN")
    src = EnvironSource(env_prefix="APP", nested_separator="__")
    data = src.load(model=ServerModel)
    assert data["log"]["level"] == "WARN"


def test_env_json_struct_and_flat_override_order_independent() -> None:
    """Flat keys should override JSON struct keys regardless of input order."""
    first = {"LOG": '{"level":"DEBUG"}', "LOG_LEVEL": "WARN"}
    second = {"LOG_LEVEL": "WARN", "LOG": '{"level":"DEBUG"}'}

    first_data = map_env_to_model(first, ServerModel)
    second_data = map_env_to_model(second, ServerModel)

    assert first_data["log"]["level"] == "WARN"
    assert second_data["log"]["level"] == "WARN"


def test_invalid_nested_separator_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty nesting separator should raise ValueError."""
    monkeypatch.setenv("APP_HOST", "envhost")
    src = EnvironSource(env_prefix="APP", nested_separator="")
    with pytest.raises(ValueError, match="nested_separator must be a non-empty"):
        src.load(model=SimpleModel)


def test_scalar_and_literal_coercion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Primitive, union, and literal coercion should map values correctly."""
    monkeypatch.setenv("APP_LEVEL", "DEBUG")
    monkeypatch.setenv("APP_VALUE", "2")
    monkeypatch.setenv("APP_ENABLED", "true")

    assert EnvironSource(env_prefix="APP").load(model=LiteralModel)["level"] == "DEBUG"
    assert EnvironSource(env_prefix="APP").load(model=IntLiteralModel)["value"] == 2
    assert (
        EnvironSource(env_prefix="APP").load(model=BoolLiteralModel)["enabled"] is True
    )


def test_union_and_optional_nested_support(monkeypatch: pytest.MonkeyPatch) -> None:
    """Union fields and optional nested structs should be resolved/coerced."""
    monkeypatch.setenv("APP_VALUE", "123")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")

    union_data = EnvironSource(env_prefix="APP").load(model=UnionModel)
    optional_nested = EnvironSource(env_prefix="APP").load(model=OptionalNestedModel)

    assert union_data["value"] == 123
    assert optional_nested["log"]["level"] == "DEBUG"


def test_no_model_returns_flat_lowercase(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no model is provided, returned keys should be lowercase flat names."""
    monkeypatch.setenv("APP_FOO", "bar")
    data = EnvironSource(env_prefix="APP").load(model=None)
    assert data["foo"] == "bar"
