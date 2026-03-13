"""Tests for DataModel/DataSource core behavior."""

from typing import Any

import msgspec
import pytest

from msgspec_config import DataModel, DataSource, datasources


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
    assert from_data.__datasource_instances__ == ()
    assert from_data.get_unmapped_payload() == {}
    assert from_json.__datasource_instances__ == ()
    assert from_json.get_unmapped_payload() == {}


def test_model_helpers_support_field_aliases() -> None:
    """Constructor/from_data/from_json should accept canonical and alias keys."""

    class App(DataModel):
        host: str = msgspec.field(default="localhost", name="HOST")
        port: int = msgspec.field(default=8080, name="PORT")

    from_kwargs = App(host="kw", PORT=1)
    from_data = App.from_data({"host": "data", "PORT": 2})
    from_json = App.from_json('{"host":"json","PORT":3}')

    assert from_kwargs.host == "kw"
    assert from_kwargs.port == 1
    assert from_data.host == "data"
    assert from_data.port == 2
    assert from_json.host == "json"
    assert from_json.port == 3


def test_model_json_schema_returns_json() -> None:
    """Schema helper should return a JSON string payload."""

    class App(DataModel):
        host: str = "localhost"

    schema_text = App.model_json_schema()
    assert schema_text.startswith("{")
    assert '"type"' in schema_text


def test_model_stores_datasource_instances() -> None:
    """Model instances should keep cloned runtime datasource instances."""

    src = _StaticSource(payload={"host": "source"})

    @datasources(src)
    class App(DataModel):
        host: str = "default"

    model = App()

    assert model.host == "source"
    assert len(model.__datasource_instances__) == 1
    assert model.__datasource_instances__[0] is not src


def test_get_unmapped_payload_includes_unknown_constructor_kwargs() -> None:
    """Unknown constructor kwargs should be exposed in unmapped payload."""

    class App(DataModel):
        host: str = "default"

    model = App(host="x", hots="typo")

    assert model.host == "x"
    assert model.get_unmapped_payload() == {"hots": "typo"}


def test_get_unmapped_payload_merges_source_order_and_is_cached() -> None:
    """Method should deep-merge source unmapped values and cache."""

    class UnmappedSource(DataSource):
        payload: dict[str, Any] = {}
        unmapped_payload: dict[str, Any] = {}

        def load(
            self,
            model: type[DataModel] | None = None,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            return dict(self.payload), dict(self.unmapped_payload)

    @datasources(
        UnmappedSource(
            payload={"host": "first"},
            unmapped_payload={"debug": {"a": 1}, "shared": {"x": 1}},
        ),
        UnmappedSource(
            payload={"host": "second"},
            unmapped_payload={"debug": {"b": 2}, "shared": {"y": 2}},
        ),
    )
    class App(DataModel):
        host: str = "default"

    model = App(shared={"y": "from_kwargs"}, extraneous=True)
    first = model.get_unmapped_payload()
    second = model.get_unmapped_payload()

    assert model.host == "second"
    assert first == {
        "debug": {"a": 1, "b": 2},
        "shared": {"x": 1, "y": "from_kwargs"},
        "extraneous": True,
    }
    assert second == first
    assert model.__unmapped_cache__ == first


def test_reserved_runtime_attribute_name_raises() -> None:
    """Declaring runtime-reserved names should fail."""
    with pytest.raises(TypeError, match="reserved"):

        class BadModel(DataModel):
            __unmapped_cache__: dict[str, Any] = {}


def test_frozen_model_supports_internal_runtime_state_assignment() -> None:
    """Frozen DataModel instances should still receive runtime internal state."""

    class RuntimeSource(DataSource):
        def load(
            self,
            model: type[DataModel] | None = None,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            self._set_raw_argv(["command", "test"])
            return {"host": "source"}, {"unknown": "value"}

    @datasources(RuntimeSource())
    class FrozenApp(DataModel, frozen=True):
        host: str = "default"

    model = FrozenApp(extra=True)

    assert model.host == "source"
    assert model.get_unmapped_payload() == {"unknown": "value", "extra": True}
    assert model.get_raw_argv() == ["command", "test"]


def test_frozen_datasource_supports_runtime_state_assignment() -> None:
    """Frozen DataSource instances should support runtime state updates."""

    class FrozenSource(DataSource, frozen=True):
        def load(
            self,
            model: type[DataModel] | None = None,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            self._set_raw_argv(["leftover"])
            return {"host": "from-source"}, {"unknown": 1}

    class App(DataModel):
        host: str = "default"

    src = FrozenSource()
    data = src.resolve(model=App)

    assert data == {"host": "from-source"}
    assert src.__unmapped_kwargs__ == {"unknown": 1}
    assert src.__raw_argv__ == ["leftover"]
