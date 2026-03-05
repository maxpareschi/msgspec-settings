"""Tests for YAML datasource behavior."""

from pathlib import Path

import msgspec
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


def test_unmapped_yaml_keys_are_stored_on_source(tmp_path: Path) -> None:
    """Unknown YAML keys should be split out into source unmapped runtime state."""

    class Log(msgspec.Struct, kw_only=True):
        level: str = "INFO"

    class Model(msgspec.Struct, kw_only=True):
        host: str = "localhost"
        log: Log = msgspec.field(default_factory=Log)

    path = tmp_path / "config.yaml"
    path.write_text(
        "host: example.com\nunknown: 1\nlog:\n  level: DEBUG\n  levle: typo\n",
        encoding="utf-8",
    )

    src = YamlSource(yaml_path=str(path))
    data = src.resolve(model=Model)

    assert data == {"host": "example.com", "log": {"level": "DEBUG"}}
    assert src.__unmapped_kwargs__ == {"unknown": 1, "log": {"levle": "typo"}}


def test_yaml_alias_fields_are_supported_on_resolve(tmp_path: Path) -> None:
    """Canonical YAML keys should resolve to alias output paths."""

    class AliasLog(msgspec.Struct, kw_only=True):
        level: str = msgspec.field(default="INFO", name="LEV")

    class AliasModel(msgspec.Struct, kw_only=True):
        port: int = msgspec.field(default=8080, name="PORT_NUMBER")
        log: AliasLog = msgspec.field(default_factory=AliasLog, name="LOGGER")

    path = tmp_path / "config.yaml"
    path.write_text("port: 9000\nlog:\n  level: WARN\n", encoding="utf-8")

    data = YamlSource(yaml_path=str(path)).resolve(model=AliasModel)
    assert data == {"PORT_NUMBER": 9000, "LOGGER": {"LEV": "WARN"}}
