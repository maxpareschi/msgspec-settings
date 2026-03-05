# msgspec-settings

Typed configuration loading on top of `msgspec`.

This package exposes a small API:
- `DataModel`: typed config model base class
- `DataSource`: source base class
- `datasources(...)`: class decorator for source composition
- `entry(...)` / `group(...)`: field declaration helpers
- Built-in sources: `TomlSource`, `YamlSource`, `DotEnvSource`, `EnvironSource`, `CliSource`

## Installation

```bash
pip install msgspec-settings
```

## Quick Start

```python
from msgspec_settings import (
    CliSource,
    DataModel,
    DotEnvSource,
    EnvironSource,
    TomlSource,
    datasources,
    entry,
)


@datasources(
    TomlSource(toml_path="config.toml"),
    DotEnvSource(dotenv_path=".env", env_prefix="APP"),
    EnvironSource(env_prefix="APP"),
    CliSource(),
)
class AppConfig(DataModel):
    host: str = entry("localhost", min_length=1)
    port: int = 8080
    debug: bool = False


cfg = AppConfig()
print(cfg.model_dump())
```

Merge precedence is left-to-right by source, then constructor kwargs:

```
defaults < source_1 < source_2 < ... < source_n < kwargs
```

## Core API

### `DataModel`

`DataModel` subclasses `msgspec.Struct` with `kw_only=True`.

Methods:
- `from_data(data: dict[str, Any]) -> Self`
- `from_json(json_str: str | bytes) -> Self`
- `model_dump() -> dict[str, Any]`
- `model_dump_json(indent: int = 0) -> str`
- `model_json_schema(indent: int = 0) -> str`
- `from_datasources(*datasource_args, **kwargs) -> Mapping[str, Any]`

Notes:
- Positional arguments are rejected.
- Unknown keys are handled by `msgspec.convert` default behavior.

### `DataSource`

Base class for all data providers.

Implement:
- `load(model: type[DataModel] | None = None) -> dict[str, Any]`

Sources are cloned per model instantiation before `load` is called to avoid
shared mutable state issues.

### `datasources(*sources)`

Class decorator that attaches source templates to a model class.

```python
@datasources(TomlSource(toml_path="config.toml"))
class Settings(DataModel):
    port: int = 8080
```

### `entry(...)` and `group(...)`

Use `entry(...)` when you want msgspec `Meta` validation metadata while keeping
safe mutable defaults:

```python
from msgspec_settings import DataModel, entry


class ApiConfig(DataModel):
    host: str = entry("localhost", min_length=1)
    tags: list[str] = entry([], description="Allowed tags")
```

Use `group(...)` for grouped fields inferred from their annotations:

```python
from msgspec_settings import DataModel, group


class Child(DataModel):
    value: int = 1


class Parent(DataModel):
    child: Child = group(collapsed=True)
    children: list[Child] = group(mutable=True)
```

## Built-in Sources

Built-ins are available from both the package root and
`msgspec_settings.sources`.

### `TomlSource`

Loads mapping data from a TOML file via `msgspec.toml.decode`.

Fields:
- `toml_path: str | None = None`
- `toml_encoding: str = "utf-8"`

### `YamlSource`

Loads mapping data from a YAML file via `msgspec.yaml.decode`.

Fields:
- `yaml_path: str | None = None`
- `yaml_encoding: str = "utf-8"`

### `DotEnvSource`

Parses `.env` files and optionally maps keys onto a target model.

Fields:
- `dotenv_path: str = ".env"`
- `dotenv_encoding: str = "utf-8"`
- `env_prefix: str = ""`
- `nested_separator: str = "_"`

### `EnvironSource`

Loads data from `os.environ`, optionally filtered by prefix and mapped onto a
target model.

Fields:
- `env_prefix: str = ""`
- `nested_separator: str = "_"`

### `CliSource`

Builds CLI options from model fields using `rich_click`.

Fields:
- `cli_args: list[str] | None = None` (defaults to `sys.argv[1:]`)
- `kebab_case: bool = True`
- `theme: str = "cargo-slim"`

Additional property:
- `cli_extra_args: list[str]` containing unknown/extra CLI args from last parse.

## Development

Run tests:

```bash
python -m pytest -q
```
