"""Tests for YAML datasource behavior."""

from pathlib import Path

import pytest

from msgspec_settings import YamlSource


def test_empty_path_returns_empty() -> None:
    """Unset path should yield empty mapping."""
    assert YamlSource().load() == {}


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """Missing file should be treated as absent source."""
    src = YamlSource(yaml_path=str(tmp_path / "missing.yaml"))
    assert src.load() == {}


def test_load_valid_yaml(tmp_path: Path) -> None:
    """Valid YAML content should decode into a mapping."""
    path = tmp_path / "config.yaml"
    path.write_text("host: example.com\nport: 9000\n", encoding="utf-8")
    data = YamlSource(yaml_path=str(path)).load()
    assert data["host"] == "example.com"
    assert data["port"] == 9000


def test_invalid_yaml_raises_runtime_error(tmp_path: Path) -> None:
    """Parse failures should surface as RuntimeError with context."""
    path = tmp_path / "broken.yaml"
    path.write_text("host: [", encoding="utf-8")
    src = YamlSource(yaml_path=str(path))
    with pytest.raises(RuntimeError, match="Failed to parse YAML"):
        src.load()
