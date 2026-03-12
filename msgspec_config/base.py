"""Core model and source abstractions for ``msgspec_config``.

This module defines:
- :class:`DataModel`, the typed configuration container.
- :class:`DataSource`, the source contract used to produce mapping patches.
- :func:`datasources`, the class decorator used to bind source templates.
"""

import copy

from collections.abc import Mapping
from threading import Lock
from typing import ClassVar, Any, Self

import msgspec

from .fields import apply_entry_defaults
from .merge import deep_merge_into
from .mapping import (
    split_mapping_by_model_fields,
    split_top_level_mapping_by_model_fields,
)


_JSON_ENCODER: msgspec.json.Encoder | None = None
_LOCK: Lock = Lock()


def get_json_encoder() -> msgspec.json.Encoder:
    """Return the process-wide JSON encoder singleton.

    Returns:
        Shared :class:`msgspec.json.Encoder` instance.
    """
    global _JSON_ENCODER
    with _LOCK:
        if _JSON_ENCODER is None:
            _JSON_ENCODER = msgspec.json.Encoder()
        return _JSON_ENCODER


class DataModelMeta(msgspec.StructMeta):
    """Metaclass enforcing ``DataModel`` conventions and load behavior."""

    def __new__(
        cls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type["DataModel"]:
        """Create a ``DataModel`` or ``DataSource`` subclass.

        Args:
            name: Class name being created.
            bases: Tuple of base classes.
            namespace: Mutable class namespace.
            **kwargs: Additional ``msgspec.Struct`` options.

        Returns:
            Created class object.

        Raises:
            TypeError: If a reserved runtime attribute is declared as a field.
        """
        if not any(isinstance(base, DataModelMeta) for base in bases):
            return super().__new__(cls, name, bases, namespace, **kwargs)

        reserved_attributes = {
            "__json_encoder__",
            "__json_decoder__",
            "__schema__",
            "__datasource_defs__",
            "__datasource_instances__",
            "__constructor_unmapped__",
            "__unmapped_cache__",
            "__unmapped_kwargs__",
            "__raw_argv__",
        }

        for attr in reserved_attributes:
            if attr in namespace:
                raise TypeError(f"Attribute {attr} is reserved")

        annotations = namespace.get("__annotations__", {})
        for field_name in annotations:
            if field_name in reserved_attributes:
                raise TypeError(f"Field name {field_name} is reserved")

        kwargs.setdefault("kw_only", True)
        kwargs.setdefault("dict", True)

        apply_entry_defaults(
            namespace=namespace, reserved_attributes=reserved_attributes
        )

        return super().__new__(cls, name, bases, namespace, **kwargs)

    def __call__(cls: type["DataModel"], *args: Any, **kwargs: Any) -> "DataModel":
        """Instantiate and validate a ``DataModel`` instance.

        For regular models, configured datasource definitions are cloned,
        loaded, and merged before final conversion. For ``DataSource``
        subclasses, this method behaves like normal struct instantiation.

        Args:
            *args: Positional arguments. Not supported.
            **kwargs: Field values and explicit overrides. Unknown keys are
                captured on the instance and exposed via
                :meth:`DataModel.get_unmapped_payload`.

        Returns:
            Validated model instance with runtime datasource state attached,
            including unmapped payload tracking and raw argv fragments produced
            by sources.

        Raises:
            TypeError: If positional arguments are provided.
        """
        if args:
            raise TypeError(
                f"Class {cls.__name__} does not support positional arguments. "
                "Use keyword arguments instead."
            )

        prepared_kwargs, constructor_unmapped = cls._split_constructor_kwargs(kwargs)
        datasource_instances: tuple["DataSource", ...] = ()
        unmapped_cache: dict[str, Any] | None = {}

        if cls.__datasource_defs__ is not None and not issubclass(cls, DataSource):
            prepared, datasource_instances = cls._collect_datasources_payload(
                *cls.__datasource_defs__, **prepared_kwargs
            )
            unmapped_cache = None
        else:
            prepared = prepared_kwargs
            unmapped_cache = constructor_unmapped
        instance = msgspec.convert(prepared, type=cls)
        return cls._setup_instance(
            instance,
            datasource_instances=datasource_instances,
            unmapped_cache=unmapped_cache,
            constructor_unmapped=constructor_unmapped,
        )


class DataModel(msgspec.Struct, metaclass=DataModelMeta):
    """Base typed settings model with optional datasource composition.

    ``DataModel`` instances may be built from ordered datasource patches plus
    constructor keyword overrides. Source-level unmapped values and unknown
    constructor kwargs can be inspected with :meth:`get_unmapped_payload`.
    Raw argv leftovers produced by CLI-aware sources can be inspected with
    :meth:`get_raw_argv`.
    """

    __json_encoder__: ClassVar[msgspec.json.Encoder] = get_json_encoder()
    __json_decoder__: ClassVar[msgspec.json.Decoder | None] = None
    __schema__: ClassVar[dict[str, Any] | None] = None
    __datasource_defs__: ClassVar[tuple["DataSource", ...] | None] = None

    @classmethod
    def _split_payload_for_convert(
        cls,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Split payload keys into model-mapped and unmapped dictionaries.

        Args:
            payload: Raw mapping payload.

        Returns:
            Tuple ``(mapped, unmapped)`` where ``mapped`` contains only
            model-recognized keys normalized to encoded field names, and
            ``unmapped`` contains keys not recognized by ``cls``.
        """
        return split_mapping_by_model_fields(payload, cls)

    @classmethod
    def _split_constructor_kwargs(
        cls,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Split constructor kwargs into mapped and unmapped top-level keys.

        Args:
            payload: Constructor kwargs mapping.

        Returns:
            Tuple ``(mapped, unmapped)`` where ``mapped`` uses encoded
            top-level field names.
        """
        return split_top_level_mapping_by_model_fields(payload, cls)

    @classmethod
    def _prepare_payload_for_convert(
        cls,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Normalize payload keys to model-accepted field names.

        Args:
            payload: Raw mapping payload.

        Returns:
            Mapping filtered to recognized model keys and normalized to encoded
            field names.
        """
        mapped, _ = cls._split_payload_for_convert(payload)
        return mapped

    @staticmethod
    def _setup_instance(
        instance: "DataModel",
        datasource_instances: tuple["DataSource", ...] | None = None,
        unmapped_cache: dict[str, Any] | None = None,
        constructor_unmapped: Mapping[str, Any] | None = None,
    ) -> "DataModel":
        """Attach runtime datasource, unmapped, and raw-argv state.

        Args:
            instance: Model instance to mutate.
            datasource_instances: Runtime source instances used to build
                ``instance``.
            unmapped_cache: Precomputed unmapped cache, or ``None`` to defer
                computation until unmapped payload access.
            constructor_unmapped: Unmapped key/value pairs provided directly as
                constructor kwargs.

        Returns:
            Same ``instance`` with runtime attributes initialized.
            ``__raw_argv__`` is populated by concatenating per-source raw argv
            fragments in source evaluation order.
        """
        if datasource_instances is None:
            datasource_instances = ()
        instance.__datasource_instances__ = datasource_instances
        instance.__unmapped_cache__ = unmapped_cache
        instance.__constructor_unmapped__ = (
            constructor_unmapped if constructor_unmapped is not None else {}
        )
        raw_argv: list[str] = []
        for datasource in datasource_instances:
            source_raw_argv = getattr(datasource, "__raw_argv__", None)
            if isinstance(source_raw_argv, list):
                raw_argv.extend(
                    item for item in source_raw_argv if isinstance(item, str)
                )
        instance.__raw_argv__ = raw_argv
        return instance

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> Self:
        """Build an instance from a plain mapping payload.

        Args:
            data: Input mapping to validate against ``cls``.

        Returns:
            Validated model instance with empty runtime datasource state.
            Keys not recognized by ``cls`` are ignored.
        """
        prepared = cls._prepare_payload_for_convert(data)
        instance = msgspec.convert(prepared, type=cls)
        return cls._setup_instance(instance)

    @classmethod
    def from_json(cls, json_str: str | bytes) -> Self:
        """Build an instance from a JSON payload.

        Args:
            json_str: JSON string or bytes.

        Returns:
            Decoded model instance with empty runtime datasource state.
            Keys not recognized by ``cls`` are ignored.

        Raises:
            TypeError: If decoded JSON is not an object mapping.
        """
        raw = msgspec.json.decode(json_str)
        if not isinstance(raw, Mapping):
            raise TypeError("JSON payload must decode to an object mapping")
        prepared = cls._prepare_payload_for_convert(raw)
        instance = msgspec.convert(prepared, type=cls)
        return cls._setup_instance(instance)

    @classmethod
    def model_json_schema(cls, indent: int = 0) -> str:
        """Serialize the model JSON schema.

        Args:
            indent: Pretty-print indentation level. ``0`` disables formatting.

        Returns:
            JSON schema string representation.
        """
        if cls.__schema__ is None:
            cls.__schema__ = msgspec.json.schema(cls)
        json_str = cls.__json_encoder__.encode(cls.__schema__).decode()
        if indent > 0:
            return msgspec.json.format(json_str, indent=indent)
        return json_str

    @classmethod
    def get_datasources_payload(
        cls,
        *datasource_args: "DataSource",
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        """Merge payloads from datasource instances and explicit keyword values.

        Datasources are evaluated left-to-right. Explicit ``kwargs`` are merged
        last and therefore have highest precedence.

        Args:
            *datasource_args: Datasource instances to execute.
            **kwargs: Explicit field overrides. Unknown keys are ignored.

        Returns:
            Merged mapping ready for ``msgspec.convert``.

        Raises:
            TypeError: If any datasource returns a non-mapping value.
        """
        prepared_kwargs = cls._prepare_payload_for_convert(kwargs)
        merged_data, _ = cls._collect_datasources_payload(
            *datasource_args, **prepared_kwargs
        )
        return merged_data

    @classmethod
    def _collect_datasources_payload(
        cls,
        *datasource_defs: "DataSource",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], tuple["DataSource", ...]]:
        """Clone datasource definitions, load them, and merge payloads.

        Args:
            *datasource_defs: Datasource template instances bound on the class.
            **kwargs: Explicit mapped keyword overrides merged after source
                payloads.

        Returns:
            Tuple ``(merged_payload, datasource_instances)`` where
            ``datasource_instances`` are the cloned runtime instances used for
            this build.

        Raises:
            TypeError: If any source returns a non-mapping value.
        """
        merged_data: dict[str, Any] = {}
        datasource_instances: list["DataSource"] = []

        for datasource_def in datasource_defs:
            datasource_instance = datasource_def.clone()
            datasource_data = datasource_instance.resolve(model=cls)
            if not isinstance(datasource_data, Mapping):
                raise TypeError(
                    f"DataSource {datasource_def.__class__.__name__} returned a "
                    "non-mapping value"
                )

            deep_merge_into(merged_data, datasource_data)
            datasource_instances.append(datasource_instance)

        if kwargs:
            deep_merge_into(merged_data, kwargs)

        return merged_data, tuple(datasource_instances)

    def model_dump(self) -> dict[str, Any]:
        """Serialize this instance into Python builtins.

        Returns:
            ``dict`` representation containing model field values.
        """
        return msgspec.to_builtins(self)

    def model_dump_json(self, indent: int = 0) -> str:
        """Serialize this instance to JSON text.

        Args:
            indent: Pretty-print indentation level. ``0`` disables formatting.

        Returns:
            JSON string representation of the model.
        """
        json_str = self.__json_encoder__.encode(self).decode()
        if indent > 0:
            return msgspec.json.format(json_str, indent=indent)
        return json_str

    def get_unmapped_payload(self) -> dict[str, Any]:
        """Return lazily merged unmapped payload from sources and kwargs.

        Returns:
            Deep-merged mapping of source-level unmapped keys (in source order)
            plus constructor kwargs that were not recognized by the model.
            Constructor unmapped keys are merged last. A shallow copy is
            returned so callers cannot mutate the cache directly.
        """
        cached = getattr(self, "__unmapped_cache__", None)
        if isinstance(cached, dict):
            return dict(cached)

        merged: dict[str, Any] = {}
        datasource_instances = getattr(self, "__datasource_instances__", ())
        for datasource in datasource_instances:
            source_unmapped = getattr(datasource, "__unmapped_kwargs__", None)
            if isinstance(source_unmapped, Mapping) and source_unmapped:
                deep_merge_into(merged, source_unmapped)

        constructor_unmapped = getattr(self, "__constructor_unmapped__", None)
        if isinstance(constructor_unmapped, Mapping) and constructor_unmapped:
            deep_merge_into(merged, constructor_unmapped)

        self.__unmapped_cache__ = merged
        return dict(merged)

    def get_raw_argv(self) -> list[str]:
        """Return CLI argv tokens not consumed by mapped CLI options.

        Returns:
            Ordered list of leftover CLI tokens collected from runtime
            datasource instances (for example ``CliSource``). Mapped field
            options are excluded. A copy is returned.
        """
        raw_argv = getattr(self, "__raw_argv__", None)
        if isinstance(raw_argv, list):
            return list(raw_argv)

        merged: list[str] = []
        datasource_instances = getattr(self, "__datasource_instances__", ())
        for datasource in datasource_instances:
            source_raw_argv = getattr(datasource, "__raw_argv__", None)
            if isinstance(source_raw_argv, list):
                merged.extend(item for item in source_raw_argv if isinstance(item, str))

        self.__raw_argv__ = merged
        return list(merged)


class DataSource(DataModel):
    """Base class for configuration sources that emit mapping patches.

    Subclasses implement :meth:`load`. Use :meth:`resolve` to run the full
    source lifecycle (reset, normalize return shape, mapped/unmapped split,
    and runtime state persistence).
    """

    def _normalize_load_result(
        self,
        result: Mapping[str, Any] | tuple[Mapping[str, Any], Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
        """Normalize ``load`` output into ``(payload, unmapped_override)``.

        Args:
            result: Return value from ``load``.

        Returns:
            Tuple containing payload mapping and optional unmapped override.

        Raises:
            TypeError: If the return value does not follow the expected shape.
        """
        if isinstance(result, tuple):
            if len(result) != 2:
                raise TypeError(
                    f"DataSource {self.__class__.__name__} load() must return "
                    "Mapping or tuple[Mapping, Mapping]"
                )
            payload, unmapped = result
            if not isinstance(payload, Mapping) or not isinstance(unmapped, Mapping):
                raise TypeError(
                    f"DataSource {self.__class__.__name__} load() tuple must be "
                    "tuple[Mapping, Mapping]"
                )
            return payload, unmapped

        if not isinstance(result, Mapping):
            raise TypeError(
                f"DataSource {self.__class__.__name__} load() must return "
                "Mapping or tuple[Mapping, Mapping]"
            )
        return result, None

    def _reset_instance(self) -> None:
        """Reset per-load runtime state on this source instance.

        This clears any previously collected unmapped keys and raw argv
        leftovers.

        Returns:
            ``None``.
        """
        self.__unmapped_kwargs__ = {}
        self.__raw_argv__ = []

    def _set_unmapped(self, unmapped: Mapping[str, Any]) -> None:
        """Store unmapped payload values on this source instance.

        Args:
            unmapped: Mapping of keys that could not be mapped to model fields.

        Returns:
            ``None``.
        """
        self.__unmapped_kwargs__ = dict(unmapped)

    def _set_raw_argv(self, raw_argv: list[str]) -> None:
        """Store raw argv leftovers on this source instance.

        Args:
            raw_argv: Ordered CLI tokens that were not consumed as mapped
                options for the target model.
        """
        self.__raw_argv__ = list(raw_argv)

    def _split_payload_against_model(
        self,
        payload: Mapping[str, Any],
        model: type[msgspec.Struct] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Split one payload into mapped and unmapped sections.

        Args:
            payload: Raw payload produced by a source.
            model: Target model type used for key recognition.

        Returns:
            Tuple ``(mapped, unmapped)``. ``mapped`` uses encoded field names
            when ``model`` provides aliases.
        """
        if model is None:
            return dict(payload), {}
        return split_mapping_by_model_fields(payload, model)

    def _finalize_payload(
        self,
        payload: Mapping[str, Any],
        model: type[msgspec.Struct] | None,
        unmapped_override: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finalize a source payload and persist source unmapped state.

        Args:
            payload: Raw source payload.
            model: Target model type used for split logic.
            unmapped_override: Optional unmapped mapping to merge on top of
                unmapped values inferred from ``payload``.

        Returns:
            Model-mapped payload fragment that should be merged into model input.
        """
        mapped, unmapped = self._split_payload_against_model(payload, model)

        if unmapped_override is not None:
            merged_unmapped = dict(unmapped)
            deep_merge_into(merged_unmapped, unmapped_override)
            self._set_unmapped(merged_unmapped)
        else:
            self._set_unmapped(unmapped)

        return mapped

    def load(
        self,
        model: type[DataModel] | None = None,
    ) -> Mapping[str, Any] | tuple[Mapping[str, Any], Mapping[str, Any]]:
        """Return raw source data before mapping finalization.

        Subclasses should override this method to implement source-specific
        loading behavior. :meth:`resolve` performs instance reset,
        return-shape normalization, and finalize/split logic.

        Args:
            model: Optional target model requesting data.

        Returns:
            Either:
            - mapping payload to be finalized against ``model``, or
            - tuple ``(payload, unmapped_override)``.
        """
        raise NotImplementedError

    def resolve(self, model: type[DataModel] | None = None) -> dict[str, Any]:
        """Load and finalize source data for safe model merging.

        Args:
            model: Optional target model requesting data.

        Returns:
            Model-mapped payload fragment ready for merge. When ``model`` is
            provided, output keys are normalized to encoded field names.
        """
        return self._load(model)

    def _load(self, model: type[DataModel] | None = None) -> dict[str, Any]:
        """Execute source loading lifecycle for one model resolution.

        This internal wrapper clears per-instance runtime state, calls
        :meth:`load`, validates the return shape, and finalizes the mapped
        payload while persisting runtime state.

        Args:
            model: Optional target model requesting data.

        Returns:
            Model-mapped payload fragment ready for merge.

        Raises:
            TypeError: If ``load`` returns an invalid payload shape.
        """
        self._reset_instance()
        payload, unmapped_override = self._normalize_load_result(self.load(model))
        return self._finalize_payload(
            payload, model, unmapped_override=unmapped_override
        )

    def clone(self) -> Self:
        """Clone this datasource configuration.

        Returns:
            Deep-copied datasource instance suitable for per-model execution.
        """
        return copy.deepcopy(self)


def datasources(*datasource_args: DataSource):
    """Bind datasource template definitions to a ``DataModel`` class.

    Args:
        *datasource_args: Datasource templates evaluated during model
            instantiation.

    Returns:
        Decorator that writes cloned datasource templates to
        ``cls.__datasource_defs__``.
    """

    def decorator(cls: type[DataModel]) -> type[DataModel]:
        """Attach datasource templates to one model class.

        Args:
            cls: Model class being decorated.

        Returns:
            Same class with datasource definitions attached.
        """
        if datasource_args:
            cls.__datasource_defs__ = tuple(
                datasource.clone() for datasource in datasource_args
            )
        else:
            cls.__datasource_defs__ = None
        return cls

    return decorator
