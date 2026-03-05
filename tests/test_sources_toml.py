"""Tests for TOML datasource behavior."""

from pathlib import Path

import pytest

from msgspec_settings import TomlSource


def test_empty_path_returns_empty() -> None:
    """Unset path should yield empty mapping."""
    assert TomlSource().load() == {}


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """Missing file should be treated as absent source."""
    src = TomlSource(toml_path=str(tmp_path / "missing.toml"))
    assert src.load() == {}


def test_load_valid_toml(tmp_path: Path) -> None:
    """Valid TOML content should decode into a mapping."""
    path = tmp_path / "config.toml"
    path.write_text('host = "example.com"\nport = 9000\n', encoding="utf-8")
    data = TomlSource(toml_path=str(path)).load()
    assert data["host"] == "example.com"
    assert data["port"] == 9000


def test_invalid_toml_raises_runtime_error(tmp_path: Path) -> None:
    """Parse failures should surface as RuntimeError with context."""
    path = tmp_path / "broken.toml"
    path.write_text("not = [valid", encoding="utf-8")
    src = TomlSource(toml_path=str(path))
    with pytest.raises(RuntimeError, match="Failed to parse TOML"):
        src.load()
