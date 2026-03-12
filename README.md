
<p align="center">
    <img src="https://github.com/maxpareschi/msgspec-config/blob/master/docs/assets/msgspec-config-logo.svg" width="35%" alt="msgspec-config">
</p>

# msgspec-config

Typed, multi-source configuration loading on top of `msgspec`.

`msgspec-config` is for applications that need:
- one typed model for configuration shape
- multiple config inputs (files, `.env`, environment, CLI, custom providers)
- deterministic precedence across all inputs
- strict validation/coercion without writing parsing glue

The core idea is simple: define one `DataModel`, attach ordered `DataSource`s, and instantiate the model.

## API Docs
Please visit the API docs at this project's github pages site:
<a href="https://maxpareschi.github.io/msgspec-config">https://maxpareschi.github.io/msgspec-config/</a>

## Installation

```bash
pip install msgspec-config
```

```bash
uv add msgspec-config
```

Tested on `Python>=3.11`

## Quick Start (Layered Config)

`config.toml`:

```toml
host = "toml-host"
port = 7000
[log]
level = "INFO"
```

`.env`:

```dotenv
APP_PORT=7500
APP_LOG_LEVEL=DEBUG
```

```python
from msgspec_config import (
    APISource,
    CliSource,
    DataModel,
    DotEnvSource,
    EnvironSource,
    JSONSource,
    TomlSource,
    datasources,
    entry,
    group,
)


class LogConfig(DataModel):
    level: str = "WARN"
    file_path: str = "/var/log/app.log"


@datasources(
    TomlSource(toml_path="config.toml"),
    DotEnvSource(dotenv_path=".env", env_prefix="APP"),
    EnvironSource(env_prefix="APP"),
    CliSource(),
)
class AppConfig(DataModel):
    host: str = entry("127.0.0.1", min_length=1)
    port: int = entry(8080, ge=1, le=65535)
    debug: bool = False
    log: LogConfig = group(collapsed=True)


cfg = AppConfig(port=9000)
print(cfg.model_dump_json(indent=2))
```

Precedence is deterministic and intentional:

```
defaults < source_1 < source_2 < ... < source_n < kwargs
```

With the example above:
- model defaults are the baseline
- `TomlSource` overrides defaults
- `DotEnvSource` overrides TOML
- `EnvironSource` overrides `.env`
- `CliSource` overrides environment values
- constructor kwargs (`AppConfig(port=9000)`) win last

Rationale: this gives safe defaults in code, then progressive override points for deploy/runtime, while still keeping a final explicit override path in Python.

Important:
- `env_prefix` is mandatory for both `EnvironSource` and `DotEnvSource`.
- Empty/blank prefixes raise `ValueError`.

## Field Helpers (`entry` and `group`)

### `entry(...)`

Use `entry(...)` when you need validation metadata and/or safe mutable defaults.

Why it exists:
- attaches `msgspec.Meta(...)` constraints directly from field declaration
- converts mutable defaults (`list`, `dict`, `set`) into factories automatically
- supports extra UI/schema keys: `hidden_if`, `disabled_if`, `parent_group`, `ui_component`
- supports CLI include/exclude key: `cli` (`True` include, `False` exclude)
- supports CLI override keys: `cli_flag`, `cli_short_flag`

```python
from msgspec_config import DataModel, entry


class ApiConfig(DataModel):
    timeout_seconds: int = entry(30, ge=1, le=120, description="Request timeout")
    tags: list[str] = entry([], description="Dynamic tags")
```

### `group(...)`

Use `group(...)` for nested object/list/dict fields inferred from annotations.

Why it exists:
- creates safe defaults for nested structures without shared state
- adds optional UI/schema hints (`collapsed`, `mutable`)

```python
from msgspec_config import DataModel, group


class Child(DataModel):
    value: int = 1


class Parent(DataModel):
    child: Child = group(collapsed=True)
    children: list[Child] = group(mutable=True)
    by_name: dict[str, Child] = group(mutable=True)
```

Notes:
- object annotations used with `group()` must be zero-arg constructible
- `group()` is for object/list/dict-like fields, not primitive scalars

## Built-in Sources (Behavior)

All built-ins are importable from both `msgspec_config` and `msgspec_config.sources`.

When a source is used with `resolve(model=...)` (or through `@datasources(...)` on a
`DataModel`), field resolution accepts both canonical and encoded/alias names, and mapped
output keys are emitted using encoded names.

### `TomlSource` and `YamlSource`

- load mappings from files using `msgspec.toml.decode` / `msgspec.yaml.decode`
- if path is unset or missing, they return `{}` (treated as "source absent")
- parse/read failures raise `RuntimeError` with file context

### `JSONSource`

- decodes inline JSON (`json_data`) or loads JSON from `json_path`
- if both are set, `json_data` takes precedence
- if path is unset/missing, returns `{}`
- parse/read failures raise `RuntimeError` with context

### `DotEnvSource`

- parses dotenv syntax (`export`, quotes, inline comments)
- requires non-empty `env_prefix` (prefix scoping is mandatory)
- nested keys are mapped with `nested_separator` (default `_`)
- with a `model`, values are coerced to field types
- recognized keys that fail coercion are captured in source `__unmapped_kwargs__`

Example precedence inside one source:

```dotenv
APP_LOG={"level":"DEBUG"}
APP_LOG_LEVEL=WARN
```

`APP_LOG_LEVEL` overrides `APP_LOG.level`, regardless of line order.

### `EnvironSource`

Same mapping/coercion behavior as `DotEnvSource`, but reads from `os.environ`.
`env_prefix` is mandatory, and failed coercions/unmatched keys are captured in
source `__unmapped_kwargs__`.

```python
EnvironSource(env_prefix="APP", nested_separator="__")
# APP_LOG__LEVEL=ERROR -> {"log": {"level": "ERROR"}}
```

### `CliSource`

Generates options from model fields (including nested fields).

Key behavior:
- `autogenerate=True` (default): fields are exposed automatically
- `autogenerate=False`: only fields explicitly opted in via metadata are exposed
- nested fields become flags like `--log-level`
- bools support both positive and negative forms: `--debug` / `--no-debug`
- nested struct fields also accept JSON on the top-level flag:
  - `--log '{"level":"DEBUG"}'`
- explicit nested flags override keys from that JSON
- `entry(..., cli=False)` excludes a field from CLI generation
- `entry(..., cli=True)` force-includes a field when `autogenerate=False`
- `entry(..., cli_flag=..., cli_short_flag=...)` overrides generated option names for that field
- unknown CLI args are stored on source runtime state in `__unmapped_kwargs__`, accessible also through method get_unmapped_payload()
- unmatched CLI tokens (unknown flags and positionals) are stored on source runtime state in `__raw_argv__`, retrievable by method get_raw_argv()
- set `kebab_case=False` to use dotted long flags (e.g. `--log.level`)
- CLI accepts canonical and encoded/alias field names, and maps parsed values to encoded field names

Field policy precedence:
- `cli=False`: field is excluded
- `cli=True`: field is included
- `cli_flag` / `cli_short_flag` present: field is included
- otherwise inclusion follows `autogenerate`

```python
src = CliSource(autogenerate=False, cli_args=["--server-host", "api"])
data = src.resolve(model=AppConfig)
print(data)
```

```python
@datasources(CliSource())
class CliApp(DataModel):
    dev: bool = False


# argv: ["prog", "--dev", "command", "test"]
cfg = CliApp()
print(cfg.dev)  # True
print(cfg.get_raw_argv())  # ["command", "test"]
```

### `APISource`

- performs an HTTP `GET` request against `api_url`
- optional auth header via `header_name` + `header_value`
- optional `root_node` to unwrap wrapped payloads (for example `{"data": {...}}`)
- request or parse failures raise `RuntimeError` with endpoint context

```python
src = APISource(
    api_url="https://example.com/config",
    header_name="Authorization",
    header_value="Bearer <token>",
    root_node="data",
)
data = src.resolve()
```

## Custom Source Example

When built-ins are not enough, implement `DataSource.load(...)`.

```python
from typing import Any

from msgspec_config import DataModel, DataSource, datasources


class SecretsSource(DataSource):
    def load(self, model: type[DataModel] | None = None) -> dict[str, Any]:
        # Replace this with Vault/AWS/GCP/etc.
        return {"host": "secrets-host", "port": 8443}


@datasources(SecretsSource())
class ServiceConfig(DataModel):
    host: str = "localhost"
    port: int = 8080
```

Rationale: sources are deep-cloned per model instantiation, so source-local mutable state does not leak across `DataModel()` calls. `DataSource.resolve(...)` is the public finalized loader (reset + finalize); custom sources should override `load(...)`.

## Limitations

- Do not shadow `DataModel`/`DataSource` method names with fields; this is user responsibility and can break runtime behavior.

## DataModel Helpers

`DataModel` is a `msgspec.Struct` configured as keyword-only and with dict-like output support.

Useful methods:
- `from_data(data)` to create an instance from a Python mapping
- `from_json(json_str)` to create an instance from JSON bytes/string
- `model_dump()` to get the model converted in Python builtins
- `model_dump_json(indent=...)` for JSON output
- `model_json_schema(indent=...)` for JSON Schema export
- `get_datasources_payload(*sources, **kwargs)` to retrieve merged source payloads manually
- `get_unmapped_payload()` to lazily merge source runtime `__unmapped_kwargs__` in source order plus unknown constructor kwargs (merged last)
- `get_raw_argv()` to read raw CLI leftovers (unknown flags/positionals after mapped CLI options are filtered out)

Notes:
- `from_data(...)` and `from_json(...)` ignore unknown keys.
- Unknown keyword arguments passed to `DataModel(...)` are available through
  `get_unmapped_payload()`.

Example:

```python
cfg = AppConfig.from_json('{"host":"example.com","port":8081}')
print(cfg.model_dump())
print(AppConfig.model_json_schema(indent=2))
```

## API Summary

- `DataModel`: typed model base class with validation/serialization helpers
- `DataSource`: source base class (`load(model=...) -> raw mapping`, `resolve(model=...) -> finalized mapping`)
- `datasources(*sources)`: decorator that attaches ordered source templates
- `entry(...)`: field helper with validation metadata and safe mutable defaults
- `group(...)`: helper for grouped object/list/dict fields
- built-ins: `TomlSource`, `YamlSource`, `JSONSource`, `DotEnvSource`, `EnvironSource`, `CliSource`, `APISource`

## Development (Makefile + Commands)

The repository includes a `Makefile` to standardize common local tasks. Run targets from the project root.

Prerequisites:
- `uv`
- GNU Make (`make`)
- on Windows, use a GNU Make provider (for example Git Bash `make` or `mingw32-make`)

Typical workflow:

```bash
make venv   # install/update dependencies from lockfile
make ruff   # format + lint autofix
make test   # run tests
make docs   # regenerate docs in ./docs
```

Run the full local pipeline:

```bash
make all
```

`all` expands to:

```text
venv -> ruff -> test -> docs
```

Makefile targets:
- `make venv`: `uv sync`
- `make docs`: `uv run pdoc -o ./docs --docformat google --favicon assets/msgspec-config-logo.svg --logo assets/msgspec-config-logo.svg --search -t ./docs --show-source msgspec_config`
- `make ruff`: `uv run ruff format .` and `uv run ruff check --fix .`
- `make test`: `uv run pytest`
- `make build`: `uv build --clear --no-sources`
- `make publish-testpypi`: runs `make build`, then `uv publish --index testpypi`
- `make publish-pypi`: runs `make build`, then `uv publish`

Equivalent direct commands (without `make`):

```bash
uv sync
uv run ruff format .
uv run ruff check --fix .
uv run pytest
uv run pdoc -o ./docs --docformat google --favicon assets/msgspec-config-logo.svg --logo assets/msgspec-config-logo.svg --search -t ./docs --show-source msgspec_config
uv build --clear --no-sources
```

## Release (uv)

Build clean artifacts:

```bash
make build
```

Publish to TestPyPI first:

```bash
$env:UV_PUBLISH_TOKEN="pypi-<testpypi-token>"
make publish-testpypi
```

Publish to PyPI:

```bash
$env:UV_PUBLISH_TOKEN="pypi-<pypi-token>"
make publish-pypi
```

Packaging policy:
- wheel: runtime package only (`msgspec_config`)
- sdist: includes source, tests, and docs metadata for downstream builds/tests
