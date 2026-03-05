"""JSON-backed data source implementation."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import msgspec

from ..base import DataSource


class JSONSource(DataSource):
    """Load configuration data from inline JSON or a JSON file.

    Attributes:
        json_data: Inline JSON payload (string) to decode.
        json_path: Optional JSON file path used when ``json_data`` is unset.
        json_encoding: Text encoding used to read ``json_path``.
    """

    json_data: str | None = None
    json_path: str | None = None
    json_encoding: str = "utf-8"

    def load(self, model: type[msgspec.Struct] | None = None) -> Mapping[str, Any]:
        """Decode JSON configuration data.

        Args:
            model: Optional target model requesting data. Accepted for interface
                compatibility.

        Returns:
            Parsed mapping data, or an empty mapping when both inline payload
            and path are unset/missing.

        Raises:
            RuntimeError: If file reading or JSON parsing fails.
        """
        raw_data: str
        parse_context: str

        if self.json_data is not None:
            raw_data = self.json_data
            parse_context = "inline JSON payload"
        else:
            if not self.json_path:
                return {}

            path = Path(self.json_path)
            if not path.is_file():
                return {}

            try:
                raw_data = path.read_text(encoding=self.json_encoding)
            except (OSError, UnicodeDecodeError) as exc:
                raise RuntimeError(
                    f"Failed to read JSON file: {self.json_path}"
                ) from exc
            parse_context = f"JSON file: {self.json_path}"

        try:
            data: Any = msgspec.json.decode(raw_data)
        except Exception as exc:
            raise RuntimeError(f"Failed to parse {parse_context}") from exc

        if not isinstance(data, Mapping):
            return {}
        return data
