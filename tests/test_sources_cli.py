"""Tests for CLI datasource behavior and helpers."""

import sys
from typing import Annotated, Literal

import msgspec
import pytest
from msgspec import Meta

from msgspec_settings import CliSource
from msgspec_settings.sources import cli as _cli_mod

from ._models import (
    BoolLiteralModel,
    IntLiteralModel,
    LogModel,
    ServerModel,
    SimpleModel,
    UnionModel,
)


def test_make_flag_name() -> None:
    """Flag generation should support kebab and dotted notation."""
    assert _cli_mod._make_flag_name("log.file_path") == "--log-file-path"
    assert (
        _cli_mod._make_flag_name("log.file_path", kebab_case=False) == "--log.file_path"
    )


def test_python_type_to_click_mapping() -> None:
    """Type mapping helper should produce expected click option metadata."""
    import rich_click as click

    assert _cli_mod._python_type_to_click(str)["type"] is click.STRING
    assert _cli_mod._python_type_to_click(int)["type"] is click.INT
    assert _cli_mod._python_type_to_click(float)["type"] is click.FLOAT
    assert _cli_mod._python_type_to_click(bool)["is_bool_flag"] is True
    assert list(_cli_mod._python_type_to_click(Literal["a", "b"])["type"].choices) == [
        "a",
        "b",
    ]

    ann = Annotated[int, Meta(ge=0, description="port")]
    assert _cli_mod._python_type_to_click(ann)["type"] is click.INT

    struct_ann = Annotated[LogModel, Meta(description="log")]
    assert _cli_mod._python_type_to_click(struct_ann)["type"] is click.STRING


def test_parse_simple_and_nested_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI args should map to both top-level and nested fields."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--host", "clihost", "--port", "5555", "--log-level", "WARN"],
    )
    data = CliSource().resolve(model=ServerModel)
    assert data["host"] == "clihost"
    assert data["port"] == 5555
    assert data["log"]["level"] == "WARN"


def test_bool_flag_and_negation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boolean options should support both positive and --no- negated forms."""
    monkeypatch.setattr(sys, "argv", ["prog", "--debug"])
    assert CliSource().resolve(model=SimpleModel)["debug"] is True

    monkeypatch.setattr(sys, "argv", ["prog", "--no-debug"])
    assert CliSource().resolve(model=SimpleModel)["debug"] is False


def test_union_and_literal_coercion(monkeypatch: pytest.MonkeyPatch) -> None:
    """String CLI values should coerce into union and literal fields."""
    monkeypatch.setattr(sys, "argv", ["prog", "--value", "123"])
    assert CliSource().resolve(model=UnionModel)["value"] == 123

    monkeypatch.setattr(sys, "argv", ["prog", "--value", "2"])
    assert CliSource().resolve(model=IntLiteralModel)["value"] == 2

    monkeypatch.setattr(sys, "argv", ["prog", "--enabled", "true"])
    assert CliSource().resolve(model=BoolLiteralModel)["enabled"] is True


def test_invalid_literal_raises_bad_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid literal values should raise click.BadParameter."""
    import rich_click as click

    monkeypatch.setattr(sys, "argv", ["prog", "--value", "3"])
    with pytest.raises(click.BadParameter):
        CliSource().resolve(model=IntLiteralModel)


def test_json_struct_value_and_flat_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flat nested flags should override keys from JSON struct option input."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--log", '{"level":"DEBUG"}', "--log-level", "WARN"],
    )
    data = CliSource().resolve(model=ServerModel)
    assert data["log"]["level"] == "WARN"


def test_dot_notation_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """When kebab_case=False, dotted long options should be accepted."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--log.level", "ERROR", "--host", "dothost"],
    )
    data = CliSource(kebab_case=False).resolve(model=ServerModel)
    assert data["host"] == "dothost"
    assert data["log"]["level"] == "ERROR"


def test_unknown_options_are_collected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown flags should be parsed into source-level unmapped payload."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--host",
            "myhost",
            "--unknown-flag=value-1",
            "--unknown-flag",
            "value-2",
            "-x",
            "value-x",
            "positional",
        ],
    )
    src = CliSource()
    data = src.resolve(model=SimpleModel)
    assert data["host"] == "myhost"
    assert src.__unmapped_kwargs__["unknown-flag"] == ["value-1", "value-2"]
    assert src.__unmapped_kwargs__["x"] == "value-x"
    assert src.__unmapped_kwargs__["__positional__"] == ["positional"]


def test_help_exits_with_code_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """--help should terminate parsing with a successful SystemExit code."""
    monkeypatch.setattr(sys, "argv", ["prog", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        CliSource().resolve(model=SimpleModel)
    assert exc_info.value.code == 0


def test_help_uses_sys_argv_zero_as_command_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Help usage should use sys.argv[0] basename as command name."""
    monkeypatch.setattr(sys, "argv", ["my-config.py", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        CliSource().resolve(model=SimpleModel)
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = f"{captured.out}\n{captured.err}"
    assert "my-config.py" in output


def test_help_footer_and_json_text_are_rendered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Help output should include footer hints and JSON option text."""

    class HelpModel(msgspec.Struct, kw_only=True):
        debug: bool = False
        log: LogModel = msgspec.field(default_factory=LogModel)

    src = CliSource(cli_args=["--help"])
    with pytest.raises(SystemExit) as exc_info:
        src.resolve(model=HelpModel)
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = f"{captured.out}\n{captured.err}"
    assert "JSON string" in output
    assert "Untyped flags (toggles) can be negated with the --no- prefix" in output
    assert "Nested options accept a JSON string" in output


def test_alias_option_name_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alias/encoded field names should be accepted as long option names."""

    class AliasModel(msgspec.Struct, kw_only=True):
        port: int = msgspec.field(default=8080, name="PORT")

    monkeypatch.setattr(sys, "argv", ["prog", "--PORT", "7777"])
    data = CliSource().resolve(model=AliasModel)
    assert data["port"] == 7777
