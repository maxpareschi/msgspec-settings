"""Tests for entry(), group(), and apply_entry_defaults()."""

from typing import Annotated, get_args, get_origin

import pytest
from msgspec import Meta

from msgspec_config import DataModel, entry, group
import msgspec_config.fields as _fields
from msgspec_config.fields import EntryInfo


def test_entry_no_kwargs_returns_field_default() -> None:
    """entry(value) without metadata should behave like msgspec.field(default=value)."""
    result = entry(8888)
    assert result is not None
    assert not isinstance(result, EntryInfo)

    class Model(DataModel):
        port: int = result

    model = Model()
    assert model.port == 8888


def test_entry_with_meta_kwargs_rewrites_to_annotated_and_field() -> None:
    """entry(..., ge=..., le=...) should inject Annotated metadata."""

    class Model(DataModel):
        port: int = entry(8888, ge=0, le=65535)

    ann = Model.__annotations__["port"]
    assert get_origin(ann) is Annotated
    args = get_args(ann)
    assert args[0] is int
    meta = args[1]
    assert isinstance(meta, Meta)
    assert getattr(meta, "ge", None) == 0
    assert getattr(meta, "le", None) == 65535

    model = Model()
    assert model.port == 8888


def test_entry_meta_validation() -> None:
    """msgspec validation should apply injected Meta constraints."""

    class Model(DataModel):
        port: int = entry(8888, ge=0, le=65535)

    Model(port=100)
    with pytest.raises(Exception):
        Model(port=-1)
    with pytest.raises(Exception):
        Model(port=70000)


def test_entry_empty_list_uses_default_factory() -> None:
    """entry([]) should create independent list instances."""
    result = entry([])
    assert not isinstance(result, EntryInfo)

    class Model(DataModel):
        items: list[str] = result

    first = Model()
    assert first.items == []
    first.items.append("a")
    second = Model()
    assert second.items == []


def test_entry_non_empty_list_uses_default_factory_copy() -> None:
    """entry([..]) should use copy-based default factory."""
    result = entry([1, 2])
    assert not isinstance(result, EntryInfo)

    class Model(DataModel):
        items: list[int] = result

    first = Model()
    assert first.items == [1, 2]
    first.items.append(3)
    second = Model()
    assert second.items == [1, 2]


def test_entry_unknown_kwargs_raise_type_error() -> None:
    """entry() should reject unsupported kwargs."""
    with pytest.raises(TypeError, match="unsupported kwargs: my_extra"):

        class Model(DataModel):
            port: int = entry(8888, my_extra="x")


def test_entry_custom_schema_kwargs_are_mapped_to_extra_json_schema() -> None:
    """Custom UI kwargs should be stored under Meta.extra_json_schema."""

    class Model(DataModel):
        port: int = entry(
            8888,
            description="Port",
            hidden_if="staging",
            disabled_if="readonly",
            parent_group="network",
            ui_component="slider",
            cli=True,
            cli_flag="server-port",
            cli_short_flag="P",
        )

    ann = Model.__annotations__["port"]
    args = get_args(ann)
    meta = args[1]
    assert isinstance(meta, Meta)
    assert getattr(meta, "description", None) == "Port"
    extra_json_schema = getattr(meta, "extra_json_schema", None) or {}
    assert extra_json_schema.get("hidden_if") == "staging"
    assert extra_json_schema.get("disabled_if") == "readonly"
    assert extra_json_schema.get("parent_group") == "network"
    assert extra_json_schema.get("ui_component") == "slider"
    assert extra_json_schema.get("cli") is True
    assert extra_json_schema.get("cli_flag") == "server-port"
    assert extra_json_schema.get("cli_short_flag") == "P"


def test_entry_mutable_default_with_meta() -> None:
    """entry([], meta=...) should combine Meta and mutable default factory."""
    result = entry([], description="A list")
    assert isinstance(result, EntryInfo)

    class Model(DataModel):
        items: list[str] = result

    ann = Model.__annotations__["items"]
    args = get_args(ann)
    assert args[0] == list[str]
    assert getattr(args[1], "description", None) == "A list"
    model = Model()
    assert model.items == []


def test_entry_with_existing_annotated_does_not_nest() -> None:
    """entry() should append Meta metadata without nesting Annotated."""

    class Model(DataModel):
        port: Annotated[int, Meta(description="user meta")] = entry(8888, ge=0)

    ann = Model.__annotations__["port"]
    assert get_origin(ann) is Annotated
    args = get_args(ann)
    assert args[0] is int
    assert len(args) >= 2
    assert get_origin(args[0]) is not Annotated
    descriptions = [
        getattr(meta, "description", None)
        for meta in args[1:]
        if isinstance(meta, Meta)
    ]
    assert "user meta" in descriptions
    assert Model().port == 8888


def test_entry_sentinel_returned_only_when_meta_kwargs() -> None:
    """entry() should return EntryInfo only when kwargs are provided."""
    plain = entry(1)
    with_meta = entry(1, ge=0)
    assert not isinstance(plain, EntryInfo)
    assert isinstance(with_meta, EntryInfo)


def test_group_object_hint_uses_default_factory() -> None:
    """group() object hints should build independent instances."""

    class Child(DataModel):
        value: int = 1

    class Parent(DataModel):
        child: Child = group()

    first = Parent()
    second = Parent()
    assert isinstance(first.child, Child)
    assert isinstance(second.child, Child)
    assert first.child is not second.child


def test_group_list_hint_uses_default_factory() -> None:
    """group() list hints should build independent list values."""

    class Parent(DataModel):
        children: list[int] = group()

    first = Parent()
    second = Parent()
    assert first.children == []
    first.children.append(1)
    assert second.children == []


def test_group_dict_hint_uses_default_factory() -> None:
    """group() dict hints should build independent dict values."""

    class Parent(DataModel):
        by_name: dict[str, int] = group()

    first = Parent()
    second = Parent()
    assert first.by_name == {}
    first.by_name["x"] = 1
    assert second.by_name == {}


def test_group_subtypes_supported() -> None:
    """group() should support list/dict with structured element types."""

    class Child(DataModel):
        value: int = 1

    class Parent(DataModel):
        by_name: dict[str, Child] = group()
        many: list[Child] = group()

    model = Parent()
    assert model.by_name == {}
    assert model.many == []


def test_group_with_schema_flags_rewrites_to_annotated_and_field() -> None:
    """group(collapsed=..., mutable=...) should inject schema flags."""

    class Child(DataModel):
        value: int = 1

    class Parent(DataModel):
        child: Child = group(collapsed=True, mutable=True)

    ann = Parent.__annotations__["child"]
    assert get_origin(ann) is Annotated
    args = get_args(ann)
    assert args[0] is Child
    meta = args[1]
    assert isinstance(meta, Meta)
    extra_json_schema = getattr(meta, "extra_json_schema", None) or {}
    assert extra_json_schema.get("collapsed") is True
    assert extra_json_schema.get("mutable") is True


def test_group_supports_direct_meta_kwargs_and_arbitrary_schema_keys() -> None:
    """group() should accept metadata kwargs without needing Annotated."""

    class Child(DataModel):
        value: int = 1

    class Parent(DataModel):
        child: Child = group(
            description="Nested child",
            cli_short_flag="ls",
            ui_component="object-editor",
            arbitrary_hint="custom",
        )

    ann = Parent.__annotations__["child"]
    assert get_origin(ann) is Annotated
    args = get_args(ann)
    assert args[0] is Child
    meta = args[1]
    assert isinstance(meta, Meta)
    assert getattr(meta, "description", None) == "Nested child"
    extra_json_schema = getattr(meta, "extra_json_schema", None) or {}
    assert extra_json_schema.get("cli_short_flag") == "ls"
    assert extra_json_schema.get("ui_component") == "object-editor"
    assert extra_json_schema.get("arbitrary_hint") == "custom"


def test_group_metadata_merges_extra_json_schema_and_group_flags() -> None:
    """group() metadata should merge extra_json_schema and override flags."""

    class Child(DataModel):
        value: int = 1

    class Parent(DataModel):
        child: Child = group(
            collapsed=True,
            mutable=True,
            extra_json_schema={"collapsed": False, "from_meta": 1},
            from_kwargs=2,
        )

    ann = Parent.__annotations__["child"]
    args = get_args(ann)
    meta = args[1]
    assert isinstance(meta, Meta)
    extra_json_schema = getattr(meta, "extra_json_schema", None) or {}
    assert extra_json_schema.get("from_meta") == 1
    assert extra_json_schema.get("from_kwargs") == 2
    assert extra_json_schema.get("collapsed") is True
    assert extra_json_schema.get("mutable") is True


def test_group_invalid_hint_raises() -> None:
    """group() should reject unsupported annotations."""
    with pytest.raises(TypeError, match="group annotation must be object"):

        class BadTuple(DataModel):
            pair: tuple[int, int] = group()

    with pytest.raises(TypeError, match="group annotation must be object"):

        class BadInt(DataModel):
            value: int = group()

    with pytest.raises(TypeError, match="group annotation must be object"):

        class BadStr(DataModel):
            value: str = group()


def test_group_object_hint_requires_zero_arg_constructor() -> None:
    """group() object annotations must be zero-argument constructible."""

    class NeedsArg:
        def __init__(self, value: int):
            self.value = value

    with pytest.raises(TypeError, match="zero-arg constructible"):

        class BadCtor(DataModel):
            item: NeedsArg = group()


def test_group_uninspectable_object_hint_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """group() should reject objects without inspectable zero-arg signatures."""

    class Opaque:
        pass

    def _raise_signature(_obj):
        raise ValueError("no signature")

    monkeypatch.setattr(_fields.inspect, "signature", _raise_signature)

    with pytest.raises(TypeError, match="zero-arg constructible"):

        class BadOpaque(DataModel):
            item: Opaque = group()


def test_group_rejects_non_bool_flags() -> None:
    """group() should validate collapsed/mutable argument types."""
    with pytest.raises(TypeError, match="'collapsed' must be bool"):
        group(collapsed=1)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="'mutable' must be bool"):
        group(mutable="yes")  # type: ignore[arg-type]
