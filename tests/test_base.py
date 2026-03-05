"""Tests for DataModel/DataSource core behavior."""

from typing import Any

import pytest

from msgspec_settings import DataModel, DataSource, datasources


class _StaticSource(DataSource):
    """Simple source that returns a fixed payload."""

    payload: dict[str, Any] = {}

    def load(self, model: type[DataModel] | None = None) -> dict[str, Any]:
        """Return static payload."""
        return dict(self.payload)


def test_datasources_merge_and_kwargs_override() -> None:
    """Constructor kwargs must override datasource-provided values."""

    @datasources(_StaticSource(payload={"host": "source", "port": 9000}))
    class App(DataModel):
        host: str = "default"
        port: int = 8080

    model = App(port=9999)
    assert model.host == "source"
    assert model.port == 9999


def test_datasource_order_later_wins() -> None:
    """Later datasources in decorator order should override earlier values."""

    @datasources(
        _StaticSource(payload={"port": 1000}),
        _StaticSource(payload={"port": 2000}),
    )
    class App(DataModel):
        port: int = 8080

    assert App().port == 2000


def test_datasources_are_cloned_per_instantiation() -> None:
    """Per-call source cloning should prevent state carry-over."""

    class Stateful(DataSource):
        seen: int = 0

        def load(self, model: type[DataModel] | None = None) -> dict[str, Any]:
            self.seen += 1
            return {"value": self.seen}

    @datasources(Stateful())
    class App(DataModel):
        value: int = 0

    first = App()
    second = App()
    assert first.value == 1
    assert second.value == 1


def test_positional_args_raise() -> None:
    """Positional constructor arguments are intentionally unsupported."""

    class App(DataModel):
        value: int = 0

    with pytest.raises(TypeError, match="does not support positional arguments"):
        App(1)


def test_json_and_data_helpers_roundtrip() -> None:
    """from_data/from_json/model_dump helpers should roundtrip values."""

    class App(DataModel):
        host: str = "localhost"
        port: int = 8080

    from_data = App.from_data({"host": "a", "port": 1})
    from_json = App.from_json('{"host":"b","port":2}')

    assert from_data.model_dump() == {"host": "a", "port": 1}
    assert from_json.model_dump() == {"host": "b", "port": 2}


def test_model_json_schema_returns_json() -> None:
    """Schema helper should return a JSON string payload."""

    class App(DataModel):
        host: str = "localhost"

    schema_text = App.model_json_schema()
    assert schema_text.startswith("{")
    assert '"type"' in schema_text
