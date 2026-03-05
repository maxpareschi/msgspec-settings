import sys

from pathlib import Path

from timeit import timeit
from typing import Annotated

from msgspec import Meta, Struct, field, convert, to_builtins
from rich.console import Console
from rich.table import Table
from rich.pretty import Pretty
from rich import box

from msgspec_settings import DataModel, datasources, entry, group, TomlSource, CliSource


sources = (
    TomlSource(toml_path=str(Path(__file__).with_name("server_config.toml"))),
    CliSource(),
)


class LogConfig(DataModel):
    level: str = "WARN"
    file_path: str = "/var/log/app.log"


class LogConfigStruct(Struct):
    level: str = "WARN"
    file_path: str = "/var/log/app.log"


@datasources(*sources)
class AppConfigSources(DataModel):
    host: str = entry("localhost", min_length=1)
    port: int = entry(8080, ge=1, le=65535)
    debug: bool = False
    log: LogConfig = group()


class AppConfigNoSources(DataModel):
    host: str = entry("localhost", min_length=1)
    port: int = entry(8080, ge=1, le=65535)
    debug: bool = False
    log: LogConfig = group()


class AppConfigStruct(Struct):
    host: Annotated[str, Meta(min_length=1)] = "localhost"
    port: Annotated[int, Meta(ge=1, le=65535)] = 8080
    debug: bool = False
    log: Annotated[LogConfig, Meta(extra_json_schema={"collapsed": True})] = field(
        default_factory=LogConfigStruct
    )


if __name__ == "__main__":
    console = Console()
    loops = 100

    sys.argv = [
        "server_config.py",
        "--host",
        "192.168.2.13",
        "--port",
        "9000",
        "--debug",
        "true",
        "--log-level",
        "INFO",
    ]

    sources_cfg = AppConfigSources(port=9000)
    no_sources_cfg = AppConfigNoSources(port=9000)
    struct_cfg = AppConfigStruct(port=9000)

    config_table = Table(title="Configuration", show_lines=True, box=box.ROUNDED)
    config_table.add_column("Model", style="cyan")
    config_table.add_column("Values", style="white")

    config_table.add_row("AppConfigStruct", Pretty(struct_cfg))
    config_table.add_row("AppConfigNoSources", Pretty(no_sources_cfg))
    config_table.add_row("AppConfigSources", Pretty(sources_cfg))

    benchmark_table = Table(
        title=f"Benchmark ({loops} loops)",
        show_lines=True,
        box=box.ROUNDED,
    )
    benchmark_table.add_column("Target", style="cyan")
    benchmark_table.add_column("Avg ms / instantiation", justify="right", style="green")
    benchmark_table.add_column(
        "Speed vs Baseline Struct", justify="right", style="purple"
    )

    struct_dict = to_builtins(AppConfigStruct(port=9000))

    struct_ms = (
        timeit(lambda: convert(struct_dict, type=AppConfigSources), number=loops)
        / loops
        * 1000
    )
    no_sources_ms = (
        timeit(lambda: AppConfigNoSources(port=9000), number=loops) / loops * 1000
    )
    sources_ms = (
        timeit(lambda: AppConfigSources(port=9000), number=loops) / loops * 1000
    )

    benchmark_table.add_row(
        "AppConfigStruct",
        f"{struct_ms:.8f} ms",
        "1x baseline",
    )
    benchmark_table.add_row(
        "AppConfigNoSources",
        f"{no_sources_ms:.8f} ms",
        f"{(100 / (struct_ms / no_sources_ms * 100)):.2f}x slower",
    )
    benchmark_table.add_row(
        "AppConfigSources",
        f"{sources_ms:.8f} ms",
        f"{(100 / (struct_ms / sources_ms * 100)):.3f}x slower",
    )

    console.print()
    console.print(config_table)
    console.print()
    console.print(benchmark_table)
    console.print()
