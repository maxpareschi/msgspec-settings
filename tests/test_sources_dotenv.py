"""Tests for dotenv datasource behavior."""

from pathlib import Path

import msgspec
import pytest

from msgspec_settings import DotEnvSource, EnvironSource, DataModel, datasources

from ._models import ServerModel, SimpleModel


def test_dotenv_simple_file(tmp_path: Path) -> None:
    """Dotenv key/value pairs should map to typed fields."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_HOST=dotenvhost\nAPP_PORT=4000\n", encoding="utf-8")
    data = DotEnvSource(dotenv_path=str(env_file), env_prefix="APP").resolve(
        model=SimpleModel
    )
    assert data["host"] == "dotenvhost"
    assert data["port"] == 4000


def test_dotenv_json_struct_with_flat_override_order_independent(
    tmp_path: Path,
) -> None:
    """Flat nested keys should override JSON struct fields irrespective of order."""
    ordered_1 = tmp_path / "ordered_1.env"
    ordered_2 = tmp_path / "ordered_2.env"
    ordered_1.write_text(
        'APP_LOG={"level":"DEBUG"}\nAPP_LOG_LEVEL=WARN\n',
        encoding="utf-8",
    )
    ordered_2.write_text(
        'APP_LOG_LEVEL=WARN\nAPP_LOG={"level":"DEBUG"}\n',
        encoding="utf-8",
    )

    data1 = DotEnvSource(dotenv_path=str(ordered_1), env_prefix="APP").resolve(
        model=ServerModel
    )
    data2 = DotEnvSource(dotenv_path=str(ordered_2), env_prefix="APP").resolve(
        model=ServerModel
    )

    assert data1["log"]["level"] == "WARN"
    assert data2["log"]["level"] == "WARN"


def test_dotenv_parsing_comments_and_quotes(tmp_path: Path) -> None:
    """Parser should support quoted values and inline comments."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        'APP_HOST="dotenvhost" # trailing comment\n'
        "APP_PORT=4000 # trailing comment\n"
        "APP_TAG=value#fragment\n",
        encoding="utf-8",
    )

    data = DotEnvSource(dotenv_path=str(env_file), env_prefix="APP").resolve(model=None)
    assert data["host"] == "dotenvhost"
    assert data["port"] == "4000"
    assert data["tag"] == "value#fragment"


def test_unmatched_dotenv_keys_are_stored_on_source(tmp_path: Path) -> None:
    """Unmapped dotenv keys should be captured on source runtime state."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_HOST=dotenvhost\nAPP_HOTS=typo\n", encoding="utf-8")

    src = DotEnvSource(dotenv_path=str(env_file), env_prefix="APP")
    data = src.resolve(model=SimpleModel)

    assert data["host"] == "dotenvhost"
    assert src.__unmapped_kwargs__ == {"HOTS": "typo"}


def test_invalid_dotenv_values_are_stored_on_source(tmp_path: Path) -> None:
    """Recognized dotenv keys with failed coercion should be unmapped."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_PORT=not-int\n", encoding="utf-8")

    src = DotEnvSource(dotenv_path=str(env_file), env_prefix="APP")
    data = src.resolve(model=SimpleModel)

    assert data == {}
    assert src.__unmapped_kwargs__ == {"PORT": "not-int"}


def test_missing_dotenv_file_returns_empty(tmp_path: Path) -> None:
    """Missing dotenv file should return empty mapping."""
    src = DotEnvSource(dotenv_path=str(tmp_path / "missing.env"), env_prefix="APP")
    assert src.resolve(model=SimpleModel) == {}


def test_missing_env_prefix_raises(tmp_path: Path) -> None:
    """DotEnvSource should require a non-empty env_prefix."""
    env_file = tmp_path / ".env"
    env_file.write_text("HOST=dotenvhost\n", encoding="utf-8")
    src = DotEnvSource(dotenv_path=str(env_file))
    with pytest.raises(ValueError, match="env_prefix must be a non-empty"):
        src.resolve(model=SimpleModel)


def test_blank_env_prefix_raises(tmp_path: Path) -> None:
    """Whitespace env_prefix should be rejected."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_HOST=dotenvhost\n", encoding="utf-8")
    src = DotEnvSource(dotenv_path=str(env_file), env_prefix="   ")
    with pytest.raises(ValueError, match="env_prefix must be a non-empty"):
        src.resolve(model=SimpleModel)


def test_empty_nested_separator_raises(tmp_path: Path) -> None:
    """Empty nested separator should raise ValueError."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_HOST=dotenvhost\n", encoding="utf-8")
    src = DotEnvSource(
        dotenv_path=str(env_file),
        env_prefix="APP",
        nested_separator="",
    )
    with pytest.raises(ValueError, match="nested_separator must be a non-empty"):
        src.resolve(model=SimpleModel)


def test_env_and_dotenv_precedence_via_datasource_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Datasource order should determine precedence across dotenv and environ."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_HOST=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("APP_HOST", "from_environ")

    @datasources(
        DotEnvSource(dotenv_path=str(env_file), env_prefix="APP"),
        EnvironSource(env_prefix="APP"),
    )
    class DotenvFirst(DataModel):
        host: str = "default"

    @datasources(
        EnvironSource(env_prefix="APP"),
        DotEnvSource(dotenv_path=str(env_file), env_prefix="APP"),
    )
    class EnvFirst(DataModel):
        host: str = "default"

    assert DotenvFirst().host == "from_environ"
    assert EnvFirst().host == "from_dotenv"


def test_dotenv_os_error_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reader errors should surface as RuntimeError with file context."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("APP_HOST=from_dotenv\n", encoding="utf-8")

    def _raise_os_error(_path: str, encoding: str = "utf-8") -> dict[str, str]:
        raise OSError("read error")

    monkeypatch.setattr(
        "msgspec_settings.sources.dotenv.parse_dotenv_file", _raise_os_error
    )
    src = DotEnvSource(dotenv_path=str(dotenv_path), env_prefix="APP")
    with pytest.raises(RuntimeError, match="Failed to read dotenv"):
        src.resolve(model=SimpleModel)


def test_dotenv_alias_fields_are_supported(tmp_path: Path) -> None:
    """Alias dotenv keys should map to alias output paths expected by msgspec."""

    class AliasLog(msgspec.Struct, kw_only=True):
        level: str = msgspec.field(default="INFO", name="LEV")

    class AliasModel(msgspec.Struct, kw_only=True):
        port: int = msgspec.field(default=8080, name="PORT_NUMBER")
        log: AliasLog = msgspec.field(default_factory=AliasLog, name="LOGGER")

    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_PORT_NUMBER=9000\nAPP_LOGGER_LEV=WARN\n",
        encoding="utf-8",
    )

    data = DotEnvSource(dotenv_path=str(env_file), env_prefix="APP").resolve(
        model=AliasModel
    )
    assert data == {"PORT_NUMBER": 9000, "LOGGER": {"LEV": "WARN"}}
