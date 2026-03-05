import sys
from pathlib import Path
from msgspec_settings import DataModel, datasources, entry, group, TomlSource, CliSource
from typing import Annotated


from msgspec import Meta, Struct, field

from timeit import timeit


class LogConfig(DataModel):
    level: str = "WARN"
    file_path: str = "/var/log/app.log"


class LogConfigStruct(Struct):
    level: str = "WARN"
    file_path: str = "/var/log/app.log"


@datasources(
    TomlSource(toml_path=str(Path(__file__).with_name("server_config.toml"))),
    CliSource(),
)
class AppConfigSources(DataModel):
    host: str = entry("localhost", min_length=1)
    port: int = entry(8080, ge=1, le=65535)
    debug: bool = False
    log: LogConfig = group(collapsed=True)


class AppConfigNoSources(DataModel):
    host: str = entry("localhost", min_length=1)
    port: int = entry(8080, ge=1, le=65535)
    debug: bool = False
    log: LogConfig = group(collapsed=True)


class AppConfigStruct(DataModel):
    host: Annotated[str, Meta(min_length=1)] = "localhost"
    port: Annotated[int, Meta(ge=1, le=65535)] = 8080
    debug: bool = False
    log: Annotated[LogConfig, Meta(extra_json_schema={"collapsed": True})] = field(
        default_factory=LogConfigStruct
    )


if __name__ == "__main__":
    loops = 1000

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

    print("\n<----- Configuration ----->\n")

    print(sources_cfg)
    print(no_sources_cfg)
    print(struct_cfg)

    print("\n<----- Benchmark ----->\n")

    print(
        "AppConfigSources (instantiation):",
        timeit(lambda: AppConfigSources(port=9000), number=loops) / loops * 1000,
        "ms",
    )
    print(
        "AppConfigNoSources (instantiation):",
        timeit(lambda: AppConfigNoSources(port=9000), number=loops) / loops * 1000,
        "ms",
    )
    print(
        "AppConfigStruct (instantiation):",
        timeit(lambda: AppConfigStruct(port=9000), number=loops) / loops * 1000,
        "ms",
    )
