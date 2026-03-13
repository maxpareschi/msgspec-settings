from typing import Literal

from pathlib import Path


from msgspec_config import (
    CliSource,
    DataModel,
    DataSource,
    EnvironSource,
    TomlSource,
    datasources,
    entry,
    group,
)


def _setup_config_sources() -> tuple[DataSource, ...]:
    """Setup the configuration sources for HoundConfig DataModel."""
    config_sources = []
    config_path = Path(
        "C:/Users/maxpa/Documents/Dev/Hound/hound/resources/config/hound.toml"
    )
    if config_path is not None:
        config_sources.append(TomlSource(toml_path=config_path.as_posix()))
    config_sources.append(EnvironSource(env_prefix="HOUND"))
    config_sources.append(CliSource())
    return tuple(config_sources)


class LogConfig(DataModel, frozen=True):
    """Logging configuration options."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = entry(
        "INFO", cli_short_flag="ll"
    )
    show_title: bool = entry(True, cli=False)
    show_time: bool = entry(True, cli=False)
    show_level: bool = entry(True, cli=False)
    show_path: bool = entry(True, cli=False)
    style_message: bool = entry(True, cli=False)
    file_path: str | None = None
    file_max_bytes: int = 1024 * 1024 * 5
    file_backup_count: int = 5
    silence_loggers: list[str] | None = entry(["PIL", "uvicorn", "litestar"], cli=False)
    capture_all_loggers: bool = entry(True, cli=False)


class LocalServerConfig(DataModel, frozen=True):
    """Local WS/HTTP server configuration options."""

    host: str = entry("127.0.0.1", cli_short_flag="lsh")
    port: int = entry(8888, cli_short_flag="lsp")
    cert_file: str = ""
    key_file: str = ""


@datasources(*_setup_config_sources())
class HoundConfig(DataModel, frozen=True):
    """Main application configuration.

    Auto-loads from multiple sources in order:
    1. Defaults (defined below)
    2. TOML file (if exists)
    3. Environment variables (HOUND_ prefix)
    4. CLI arguments

    Each source overrides previous ones.
    """

    dev: bool = False
    staging: bool = False
    headless: bool = False

    log: LogConfig = group()
    local_server: LocalServerConfig = group(cli_short_flag="ls")


if __name__ == "__main__":
    config = HoundConfig()
    print(config)
    print(config.model_dump_json(indent=2))
    print(config.model_json_schema(indent=2))
    config.dev = True
