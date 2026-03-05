"""HTTP API-backed data source implementation."""

from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import msgspec

from ..base import DataSource


class APISource(DataSource):
    """Load configuration data by calling an HTTP JSON endpoint.

    Attributes:
        api_url: Endpoint URL used for the GET request.
        header_name: Optional request header name (for auth, etc.).
        header_value: Optional request header value.
        root_node: Optional top-level JSON key to unwrap from response payload.
        timeout_seconds: Request timeout in seconds.
    """

    api_url: str | None = None
    header_name: str | None = None
    header_value: str | None = None
    root_node: str | None = None
    timeout_seconds: float = 10.0

    def load(self, model: type[msgspec.Struct] | None = None) -> Mapping[str, Any]:
        """Fetch and decode endpoint JSON into mapping form.

        The ``model`` parameter is accepted for interface compatibility and is
        not used in this source.

        Args:
            model: Optional model type requesting data.

        Returns:
            Parsed mapping data, or an empty mapping when URL is unset or the
            selected payload node is missing/non-mapping.

        Raises:
            ValueError: If only one of ``header_name``/``header_value`` is set.
            RuntimeError: If request fails or response JSON is invalid.
        """
        if not self.api_url:
            return {}

        if (self.header_name is None) != (self.header_value is None):
            raise ValueError("header_name and header_value must be set together")

        headers: dict[str, str] = {}
        if self.header_name is not None and self.header_value is not None:
            headers[self.header_name] = self.header_value

        request = Request(self.api_url, headers=headers, method="GET")

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_data = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Failed to fetch API endpoint: {self.api_url}") from exc

        try:
            data: Any = msgspec.json.decode(raw_data)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to parse API response JSON: {self.api_url}"
            ) from exc

        if self.root_node:
            if not isinstance(data, Mapping):
                return {}
            data = data.get(self.root_node)

        if not isinstance(data, Mapping):
            return {}
        return data
