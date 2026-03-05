"""Environment-variable-backed data source implementation."""

import os
from typing import Any

import msgspec

from ..base import DataSource
from ..mapping import map_env_to_model


class EnvironSource(DataSource):
    """Load configuration data from process environment variables.

    Attributes:
        env_prefix: Prefix used to select environment variables.
        nested_separator: Separator used to represent nesting in env keys.
    """

    env_prefix: str = ""
    nested_separator: str = "_"

    def load(self, model: type[msgspec.Struct] | None = None) -> dict[str, Any]:
        """Read environment variables and map them into configuration data.

        Args:
            model: Optional target model used for key resolution and coercion.

        Returns:
            Mapping of configuration values. When model is ``None``, returns a
            flat mapping with lowercased keys.
        """
        prefix_upper = self.env_prefix.upper()
        if prefix_upper and not prefix_upper.endswith("_"):
            prefix_upper += "_"
        prefix_len = len(prefix_upper)

        if prefix_upper:
            env_data: dict[str, str] = {}
            for key, value in os.environ.items():
                key_upper = key.upper()
                if key_upper.startswith(prefix_upper):
                    stripped = key_upper[prefix_len:]
                    if stripped:
                        env_data[stripped] = value
        else:
            env_data = {key.upper(): value for key, value in os.environ.items()}

        if not env_data:
            return {}

        if model is not None:
            return map_env_to_model(env_data, model, self.nested_separator)

        return {key.lower(): value for key, value in env_data.items()}
