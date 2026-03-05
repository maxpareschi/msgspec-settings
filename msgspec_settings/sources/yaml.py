"""YAML-backed data source implementation."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import msgspec

from ..base import DataSource


class YamlSource(DataSource):
    """Load configuration data from a YAML file.

    Attributes:
        yaml_path: Path to the YAML file to load.
        yaml_encoding: Text encoding used to read the file.
    """

    yaml_path: str | None = None
    yaml_encoding: str = "utf-8"

    def load(self, model: type[msgspec.Struct] | None = None) -> Mapping[str, Any]:
        """Read and parse YAML configuration data.

        Args:
            model: Optional target model requesting data. Accepted for interface
                compatibility.

        Returns:
            Parsed mapping data. Returns an empty mapping when path is
            unset/missing.

        Raises:
            RuntimeError: If file reading or YAML parsing fails.
        """
        if not self.yaml_path:
            return {}

        path = Path(self.yaml_path)
        if not path.is_file():
            return {}

        try:
            raw_data = path.read_text(encoding=self.yaml_encoding)
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Failed to read YAML file: {self.yaml_path}") from exc

        try:
            data: Any = msgspec.yaml.decode(raw_data)
        except Exception as exc:
            raise RuntimeError(f"Failed to parse YAML file: {self.yaml_path}") from exc

        if not isinstance(data, Mapping):
            return {}
        return data
