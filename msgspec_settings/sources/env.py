"""Environment-variable-backed data source implementation."""

import os
from typing import Any

import msgspec

from ..base import DataSource
from ..mapping import map_env_to_model


class EnvironSource(DataSource):
    """Load configuration data from process environment variables.

    Attributes:
        env_prefix: Required prefix used to select environment variables (MANDATORY!).
        nested_separator: Separator used to represent nesting in env keys.
    """

    env_prefix: str = ""
    nested_separator: str = "_"

    def load(
        self,
        model: type[msgspec.Struct] | None = None,
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        """Read process environment variables and map them to config data.

        Args:
            model: Optional target model used for key resolution and coercion.

        Returns:
            When ``model`` is ``None``, a flat lowercase mapping.
            Otherwise ``(mapped, unmatched)`` where unmatched keys are captured
            as source unmapped runtime state by the ``DataSource`` wrapper.
            Field resolution accepts canonical and encoded names, and mapped
            keys are emitted as encoded names.

        Raises:
            ValueError: If ``env_prefix`` is empty.
        """
        if not isinstance(self.env_prefix, str) or self.env_prefix.strip() == "":
            raise ValueError("env_prefix must be a non-empty string")

        prefix_upper = self.env_prefix.strip().upper()
        if not prefix_upper.endswith("_"):
            prefix_upper += "_"
        prefix_len = len(prefix_upper)

        env_data: dict[str, str] = {}
        for key, value in os.environ.items():
            key_upper = key.upper()
            if key_upper.startswith(prefix_upper):
                stripped = key_upper[prefix_len:]
                if stripped:
                    env_data[stripped] = value

        if not env_data:
            return {}

        if model is not None:
            mapped, unmatched = map_env_to_model(
                env_data,
                model,
                self.nested_separator,
                collect_unmatched=True,
            )
            return mapped, unmatched

        return {key.lower(): value for key, value in env_data.items()}
