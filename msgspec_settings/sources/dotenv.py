"""Dotenv file-backed data source implementation."""

from pathlib import Path
from typing import Any

import msgspec

from ..base import DataSource
from ..mapping import map_env_to_model

BOM = "\ufeff"
EXPORT_LEN = 6


def _find_closing_quote(value: str, quote: str) -> int:
    """Find the first non-escaped closing quote in a quoted value.

    Args:
        value: Candidate value including opening quote.
        quote: Quote character to match (``"`` or ``'``).

    Returns:
        Index of the closing quote, or ``-1`` when not found.
    """
    escaped = False
    for idx in range(1, len(value)):
        char = value[idx]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return idx
    return -1


def parse_dotenv_file(file_path: str, encoding: str = "utf-8") -> dict[str, str]:
    """Parse a dotenv file into key/value strings.

    Supported syntax:
    - optional ``export`` prefix
    - single/double quoted values
    - common escaped characters in double quotes
    - inline comments for unquoted values

    Args:
        file_path: Dotenv file path.
        encoding: Text encoding used to read the file.

    Returns:
        Parsed key/value mapping.
    """
    env_vars: dict[str, str] = {}

    with open(file_path, encoding=encoding) as handle:
        content = handle.read()

    if content.startswith(BOM):
        content = content[1:]

    for raw_line in content.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if (
            line.startswith("export")
            and len(line) > EXPORT_LEN
            and line[EXPORT_LEN].isspace()
        ):
            line = line[EXPORT_LEN:].lstrip()

        key, separator, value = line.partition("=")
        if not separator:
            continue

        key = key.strip()
        if not key.isidentifier():
            continue

        value = value.lstrip()
        if not value:
            env_vars[key] = ""
            continue

        quote = value[0]
        if quote in ('"', "'"):
            closing_idx = _find_closing_quote(value, quote)
            if closing_idx == -1:
                env_vars[key] = value.strip()
                continue

            trailing = value[closing_idx + 1 :].strip()
            if trailing and not trailing.startswith("#"):
                env_vars[key] = value.strip()
                continue

            value_content = value[1:closing_idx]
            if quote == '"' and "\\" in value_content:
                value_content = (
                    value_content.replace("\\n", "\n")
                    .replace("\\r", "\r")
                    .replace("\\t", "\t")
                    .replace('\\"', '"')
                    .replace("\\\\", "\\")
                )
            elif quote == "'" and "\\'" in value_content:
                value_content = value_content.replace("\\'", "'")

            env_vars[key] = value_content
            continue

        # Strip inline comments only when `#` is preceded by whitespace.
        for idx, char in enumerate(value):
            if char == "#" and (idx == 0 or value[idx - 1].isspace()):
                value = value[:idx]
                break
        env_vars[key] = value.strip()

    return env_vars


class DotEnvSource(DataSource):
    """Load configuration data from a dotenv file.

    Attributes:
        dotenv_path: Dotenv file path.
        dotenv_encoding: Text encoding used to read the file.
        env_prefix: Required prefix used to filter keys (MANDATORY!).
        nested_separator: Separator used to represent nesting in keys.
    """

    dotenv_path: str = ".env"
    dotenv_encoding: str = "utf-8"
    env_prefix: str = ""
    nested_separator: str = "_"

    def load(
        self,
        model: type[msgspec.Struct] | None = None,
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        """Read dotenv variables from file and map them to config data.

        Args:
            model: Optional target model used for key resolution and coercion.

        Returns:
            Mapping of model-recognized values. When ``model`` is ``None``,
            returns a flat lowercase mapping. With ``model``, field resolution
            accepts canonical and encoded names, and mapped keys are emitted as
            encoded names.

        Raises:
            ValueError: If ``env_prefix`` is empty.
            RuntimeError: If reading/parsing the file fails.
        """
        if not isinstance(self.env_prefix, str) or self.env_prefix.strip() == "":
            raise ValueError("env_prefix must be a non-empty string")

        if not self.dotenv_path:
            return {}

        path = Path(self.dotenv_path)
        if not path.is_file():
            return {}

        try:
            raw_dotenv = parse_dotenv_file(str(path), encoding=self.dotenv_encoding)
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                f"Failed to read dotenv file: {self.dotenv_path}"
            ) from exc

        if not raw_dotenv:
            return {}

        prefix_upper = self.env_prefix.strip().upper()
        if not prefix_upper.endswith("_"):
            prefix_upper += "_"
        prefix_len = len(prefix_upper)

        filtered: dict[str, str] = {}
        for key, value in raw_dotenv.items():
            key_upper = key.upper()
            if key_upper.startswith(prefix_upper):
                stripped = key_upper[prefix_len:]
                if stripped:
                    filtered[stripped] = value

        if not filtered:
            return {}

        if model is not None:
            mapped, unmatched = map_env_to_model(
                filtered,
                model,
                self.nested_separator,
                collect_unmatched=True,
            )
            return mapped, unmatched

        return {key.lower(): value for key, value in filtered.items()}
