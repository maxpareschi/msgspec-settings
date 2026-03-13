"""Field declaration helpers for DataModel classes.

This module provides:

- ``entry(...)``: field declaration helper with optional ``msgspec.Meta`` kwargs
- ``entry(...)`` extra schema keys: ``hidden_if``, ``disabled_if``,
  ``parent_group``, ``ui_component``, ``cli``, ``cli_flag``, ``cli_short_flag``
- ``group(...)``: grouped object/list/dict declaration helper with metadata
- ``apply_entry_defaults(...)``: metaclass rewrite pass used by ``DataModelMeta``
"""

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, get_args, get_origin

from msgspec import NODEFAULT, Meta, field

ENTRY_EXTRA_SCHEMA_PARAMS: frozenset[str] = frozenset(
    {
        "hidden_if",
        "disabled_if",
        "parent_group",
        "ui_component",
        "cli",
        "cli_flag",
        "cli_short_flag",
    }
)
GROUP_DISALLOWED_OBJECT_TYPES: frozenset[type[Any]] = frozenset(
    {
        object,
        bool,
        int,
        float,
        complex,
        str,
        bytes,
        bytearray,
        tuple,
        set,
        frozenset,
    }
)


def _callable_parameter_names(
    callable_obj: Any, *, exclude_self: bool = True
) -> frozenset[str]:
    """Return the parameter names of a callable.

    Args:
        callable_obj: Callable object to inspect.
        exclude_self: Whether to drop a leading ``self`` parameter.

    Returns:
        Frozen set of parameter names.
    """
    params = inspect.signature(callable_obj).parameters
    if exclude_self and params and next(iter(params)) == "self":
        return frozenset(params.keys()) - {"self"}
    return frozenset(params.keys())


META_PARAMS: frozenset[str] = _callable_parameter_names(Meta)


def _annotated_with_meta(annotation: Any, meta_obj: Meta) -> Any:
    """Attach ``meta_obj`` to annotation metadata without nesting Annotated.

    Args:
        annotation: Existing annotation.
        meta_obj: Metadata object to append.

    Returns:
        ``Annotated`` annotation containing ``meta_obj``.
    """
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        inner_type, *rest = args
        return Annotated[inner_type, *rest, meta_obj]
    return Annotated[annotation, meta_obj]


def _mutable_default_factory(value: Any) -> Any:
    """Return a default factory for mutable defaults, or ``None``.

    Args:
        value: Candidate default value.

    Returns:
        ``None`` for non-mutable defaults, otherwise a zero-arg default factory.
    """
    if type(value) not in (list, dict, set):
        return None
    value_type = type(value)
    if len(value) == 0:
        return value_type
    return lambda v=value: value_type(v)


def _to_field_default(value: Any) -> tuple[Any, Any]:
    """Convert one default value into ``(default, default_factory)``.

    Args:
        value: User-provided default value.

    Returns:
        Tuple ``(default, default_factory)`` for ``msgspec.field(...)``.
    """
    factory = _mutable_default_factory(value)
    if factory is None:
        return value, NODEFAULT
    return NODEFAULT, factory


def _build_entry_meta(meta_kwargs: dict[str, Any]) -> Meta:
    """Build a ``Meta`` instance from ``entry(...)`` keyword arguments.

    Args:
        meta_kwargs: ``entry(...)`` keyword arguments. ``msgspec.Meta``
            parameters are forwarded directly. Extra keys
            (``hidden_if``, ``disabled_if``, ``parent_group``,
            ``ui_component``, ``cli``, ``cli_flag``,
            ``cli_short_flag``) are merged into ``Meta.extra_json_schema``.

    Returns:
        Constructed ``Meta`` object.

    Raises:
        TypeError: If unsupported keyword arguments are provided.
    """
    unknown = {
        key
        for key in meta_kwargs
        if key not in META_PARAMS and key not in ENTRY_EXTRA_SCHEMA_PARAMS
    }
    if unknown:
        raise TypeError(
            "entry() received unsupported kwargs: "
            f"{', '.join(sorted(unknown))}. Allowed kwargs are msgspec.Meta "
            "parameters plus hidden_if, disabled_if, parent_group, ui_component, "
            "cli, cli_flag, cli_short_flag."
        )

    known = {k: v for k, v in meta_kwargs.items() if k in META_PARAMS}
    schema_extras = {
        k: v for k, v in meta_kwargs.items() if k in ENTRY_EXTRA_SCHEMA_PARAMS
    }

    extra_json_schema = known.pop("extra_json_schema", None) or {}
    if schema_extras:
        extra_json_schema = {**extra_json_schema, **schema_extras}
    if extra_json_schema:
        known["extra_json_schema"] = extra_json_schema
    return Meta(**known)


@dataclass(slots=True)
class EntryInfo:
    """Sentinel value produced by :func:`entry` before metaclass rewriting.

    Attributes:
        default: Field default value or ``NODEFAULT``.
        default_factory: Field default factory or ``NODEFAULT``.
        name: Optional encoded/alias field name.
        meta_kwargs: Deferred ``Meta`` keyword arguments.
    """

    default: Any
    default_factory: Any
    name: str | None
    meta_kwargs: dict[str, Any]


@dataclass(slots=True)
class GroupInfo:
    """Sentinel value produced by :func:`group` before metaclass rewriting.

    Attributes:
        collapsed: UI hint for collapsed rendering.
        mutable: UI hint indicating mutable grouped value.
        meta_kwargs: Deferred ``Meta`` keyword arguments plus arbitrary schema
            keys.
    """

    collapsed: bool
    mutable: bool
    meta_kwargs: dict[str, Any]


def entry(value: Any = NODEFAULT, *, name: str | None = None, **kwargs: Any) -> Any:
    """Declare one model field with optional ``Meta`` kwargs.

    Behavior:
    - Without extra kwargs, returns ``msgspec.field(...)`` directly.
    - With extra kwargs, returns an internal sentinel so the metaclass can
      inject ``Annotated[..., Meta(...)]`` metadata.

    Mutable defaults (``list``, ``dict``, ``set``) are converted to default
    factories to avoid shared state across instances.

    Args:
        value: Field default value.
        name: Optional encoded field name (``msgspec.field(name=...)``).
        **kwargs: ``msgspec.Meta`` arguments plus extra schema keys
            (``hidden_if``, ``disabled_if``, ``parent_group``,
            ``ui_component``), CLI include/exclude key (``cli``), and CLI
            override keys (``cli_flag``, ``cli_short_flag``). Extra keys are
            stored under ``Meta.extra_json_schema``.

    Returns:
        ``msgspec.field`` output or an ``EntryInfo`` sentinel.
    """
    field_kwargs: dict[str, Any] = {}
    if value is not NODEFAULT:
        default, default_factory = _to_field_default(value)
        field_kwargs["default"] = default
        field_kwargs["default_factory"] = default_factory
    if name is not None:
        field_kwargs["name"] = name

    if not kwargs:
        return field(**field_kwargs)

    return EntryInfo(
        default=field_kwargs.get("default", NODEFAULT),
        default_factory=field_kwargs.get("default_factory", NODEFAULT),
        name=field_kwargs.get("name"),
        meta_kwargs=kwargs,
    )


def _is_zero_arg_constructible(cls: type[Any]) -> bool:
    """Return whether ``cls`` can be called without required arguments.

    Args:
        cls: Class to inspect.

    Returns:
        ``True`` when ``cls()`` is valid without required parameters.
    """
    try:
        sig = inspect.signature(cls)
    except (TypeError, ValueError):
        return False

    for param in sig.parameters.values():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if param.default is inspect._empty:
            return False
    return True


def _group_default_factory_from_annotation(annotation: Any, field_name: str) -> Any:
    """Resolve default factory for a ``group(...)`` field from its annotation.

    Args:
        annotation: Field annotation.
        field_name: Field name, used in error messages.

    Returns:
        Default factory callable/type.

    Raises:
        TypeError: If the annotation is unsupported for ``group``.
    """
    target = annotation
    while get_origin(target) is Annotated:
        args = get_args(target)
        if not args:
            break
        target = args[0]

    origin = get_origin(target)
    if origin in (list, dict):
        return origin
    if target in (list, dict):
        return target

    if origin is None and isinstance(target, type):
        if target in GROUP_DISALLOWED_OBJECT_TYPES:
            raise TypeError(
                f"{field_name}: group annotation must be object, list[...] or dict[...] "
                f"(got {annotation!r})"
            )
        if not _is_zero_arg_constructible(target):
            raise TypeError(
                f"{field_name}: group object annotation must be zero-arg constructible "
                f"(got {annotation!r})"
            )
        return target

    raise TypeError(
        f"{field_name}: group annotation must be object, list[...] or dict[...] "
        f"(got {annotation!r})"
    )


def _build_group_meta(
    meta_kwargs: dict[str, Any], *, collapsed: bool, mutable: bool
) -> Meta:
    """Build a ``Meta`` instance from ``group(...)`` keyword arguments.

    Args:
        meta_kwargs: ``group(...)`` keyword arguments excluding
            ``collapsed``/``mutable``. ``msgspec.Meta`` parameters are
            forwarded directly. Any non-``Meta`` key is stored under
            ``Meta.extra_json_schema``.
        collapsed: Whether to inject ``collapsed=True`` schema metadata.
        mutable: Whether to inject ``mutable=True`` schema metadata.

    Returns:
        Constructed ``Meta`` object.
    """
    known = {k: v for k, v in meta_kwargs.items() if k in META_PARAMS}
    schema_extras = {k: v for k, v in meta_kwargs.items() if k not in META_PARAMS}

    extra_json_schema_raw = known.pop("extra_json_schema", None) or {}
    if isinstance(extra_json_schema_raw, Mapping):
        extra_json_schema = dict(extra_json_schema_raw)
    else:
        raise TypeError(
            "group() 'extra_json_schema' must be a mapping, "
            f"got {type(extra_json_schema_raw).__name__}"
        )

    if collapsed:
        schema_extras["collapsed"] = True
    if mutable:
        schema_extras["mutable"] = True

    if schema_extras:
        extra_json_schema = {**extra_json_schema, **schema_extras}
    if extra_json_schema:
        known["extra_json_schema"] = extra_json_schema

    return Meta(**known)


def apply_entry_defaults(
    namespace: dict[str, Any], reserved_attributes: set[str]
) -> None:
    """Rewrite class namespace entries created by ``entry`` and ``group``.

    This mutates ``namespace`` and ``namespace["__annotations__"]`` in place.
    It is intended to run in ``DataModelMeta.__new__`` before class creation.

    Args:
        namespace: Class namespace being processed.
        reserved_attributes: Field names that must not be rewritten.

    Returns:
        ``None``.
    """
    annotations = namespace.get("__annotations__", {})
    for name in list(annotations):
        if name in reserved_attributes:
            continue

        value = namespace.get(name)
        if isinstance(value, EntryInfo):
            meta_obj = _build_entry_meta(value.meta_kwargs)
            annotations[name] = _annotated_with_meta(annotations[name], meta_obj)
            namespace[name] = field(
                default=value.default,
                default_factory=value.default_factory,
                name=value.name,
            )
            continue

        if not isinstance(value, GroupInfo):
            continue

        default_factory = _group_default_factory_from_annotation(
            annotations[name], name
        )
        namespace[name] = field(default=NODEFAULT, default_factory=default_factory)

        if value.collapsed or value.mutable or value.meta_kwargs:
            meta_obj = _build_group_meta(
                value.meta_kwargs,
                collapsed=value.collapsed,
                mutable=value.mutable,
            )
            annotations[name] = _annotated_with_meta(annotations[name], meta_obj)


def group(
    *, collapsed: bool = False, mutable: bool = False, **kwargs: Any
) -> GroupInfo:
    """Declare a grouped field inferred from its type annotation.

    Supported annotation shapes:
    - object types with zero-argument constructor
    - ``list[...]``
    - ``dict[...]``

    Args:
        collapsed: Whether UI consumers should render this group collapsed.
        mutable: Whether UI consumers should treat this group as mutable.
        **kwargs: ``msgspec.Meta`` parameters plus arbitrary schema keys.
            ``Meta`` parameters are forwarded directly. Any non-``Meta`` key
            is stored under ``Meta.extra_json_schema``.

    Returns:
        ``GroupInfo`` sentinel consumed during metaclass rewriting.

    Raises:
        TypeError: If ``collapsed`` or ``mutable`` are not bool.
    """
    if type(collapsed) is not bool:
        raise TypeError(
            f"group() 'collapsed' must be bool, got {type(collapsed).__name__}"
        )
    if type(mutable) is not bool:
        raise TypeError(f"group() 'mutable' must be bool, got {type(mutable).__name__}")
    return GroupInfo(collapsed=collapsed, mutable=mutable, meta_kwargs=dict(kwargs))


__all__ = ("EntryInfo", "GroupInfo", "apply_entry_defaults", "entry", "group")
