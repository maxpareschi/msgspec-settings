"""Tests for JSON datasource behavior."""

from pathlib import Path

import msgspec
import pytest

from msgspec_settings import JSONSource


def test_empty_source_returns_empty() -> None:
    """Unset JSON payload/path should yield empty mapping."""
    assert JSONSource().load() == {}


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """Missing JSON file should be treated as absent source."""
    src = JSONSource(json_path=str(tmp_path / "missing.json"))
    assert src.load() == {}


def test_load_valid_inline_json() -> None:
    """Valid inline JSON should decode into a mapping."""
    data = JSONSource(json_data='{"host":"example.com","port":9000}').load()
    assert data["host"] == "example.com"
    assert data["port"] == 9000


def test_load_valid_json_file(tmp_path: Path) -> None:
    """Valid JSON file content should decode into a mapping."""
    path = tmp_path / "config.json"
    path.write_text('{"host":"example.com","port":9000}', encoding="utf-8")

    data = JSONSource(json_path=str(path)).load()
    assert data["host"] == "example.com"
    assert data["port"] == 9000


def test_inline_payload_takes_precedence_over_file(tmp_path: Path) -> None:
    """Inline payload should be used when both inline payload and path are set."""
    path = tmp_path / "config.json"
    path.write_text('{"host":"file-host"}', encoding="utf-8")

    data = JSONSource(
        json_data='{"host":"inline-host"}',
        json_path=str(path),
    ).load()
    assert data["host"] == "inline-host"


def test_invalid_inline_json_raises_runtime_error() -> None:
    """Inline parse failures should surface as RuntimeError with context."""
    src = JSONSource(json_data="{broken")
    with pytest.raises(RuntimeError, match="Failed to parse inline JSON payload"):
        src.load()


def test_invalid_json_file_raises_runtime_error(tmp_path: Path) -> None:
    """File parse failures should surface as RuntimeError with context."""
    path = tmp_path / "broken.json"
    path.write_text("{broken", encoding="utf-8")

    src = JSONSource(json_path=str(path))
    with pytest.raises(RuntimeError, match="Failed to parse JSON file"):
        src.load()


def test_unmapped_json_keys_are_stored_on_source() -> None:
    """Unknown JSON keys should be split out into source unmapped runtime state."""

    class Log(msgspec.Struct, kw_only=True):
        level: str = "INFO"

    class Model(msgspec.Struct, kw_only=True):
        host: str = "localhost"
        log: Log = msgspec.field(default_factory=Log)

    src = JSONSource(
        json_data='{"host":"example.com","unknown":1,"log":{"level":"DEBUG","levle":"typo"}}'
    )
    data = src.resolve(model=Model)

    assert data == {"host": "example.com", "log": {"level": "DEBUG"}}
    assert src.__unmapped_kwargs__ == {"unknown": 1, "log": {"levle": "typo"}}
