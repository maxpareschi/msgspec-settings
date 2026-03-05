"""TOML-backed data source implementation."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import msgspec

from ..base import DataSource


class TomlSource(DataSource):
    """Load configuration data from a TOML file.

    Attributes:
        toml_path: Path to the TOML file to load.
        toml_encoding: Text encoding used to read the file.
    """

    toml_path: str | None = None
    toml_encoding: str = "utf-8"

    def load(self, model: type[msgspec.Struct] | None = None) -> Mapping[str, Any]:
        """Read and parse TOML configuration data.

        Args:
            model: Optional target model requesting data. Accepted for interface
                compatibility.

        Returns:
            Parsed mapping data. Returns an empty mapping when path is
            unset/missing.

        Raises:
            RuntimeError: If file reading or TOML parsing fails.
        """
        if not self.toml_path:
            return {}

        path = Path(self.toml_path)
        if not path.is_file():
            return {}

        try:
            raw_data = path.read_text(encoding=self.toml_encoding)
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Failed to read TOML file: {self.toml_path}") from exc

        try:
            data: Any = msgspec.toml.decode(raw_data)
        except Exception as exc:
            raise RuntimeError(f"Failed to parse TOML file: {self.toml_path}") from exc

        if not isinstance(data, Mapping):
            return {}

        return data
