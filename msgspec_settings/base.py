import copy

from collections.abc import Mapping
from threading import Lock
from typing import ClassVar, Any, Self

import msgspec

from .fields import apply_entry_defaults
from .merge import deep_merge_into


_JSON_ENCODER: msgspec.json.Encoder | None = None
_LOCK: Lock = Lock()


def get_json_encoder() -> msgspec.json.Encoder:
    """Return the shared JSON encoder used by all data models.

    Returns:
        Singleton msgspec JSON encoder instance.
    """
    global _JSON_ENCODER
    with _LOCK:
        if _JSON_ENCODER is None:
            _JSON_ENCODER = msgspec.json.Encoder()
        return _JSON_ENCODER


class DataModelMeta(msgspec.StructMeta):
    """Metaclass that enforces DataModel conventions and load-on-init behavior."""

    def __new__(
        cls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type["DataModel"]:
        """Create a new DataModel/DataSource class.

        Args:
            name: Class name.
            bases: Base classes.
            namespace: Class namespace.
            **kwargs: Extra msgspec Struct options.

        Returns:
            The created class object.

        Raises:
            TypeError: If reserved attributes are explicitly declared.
        """
        if not any(isinstance(base, DataModelMeta) for base in bases):
            return super().__new__(cls, name, bases, namespace, **kwargs)

        reserved_attributes = {
            "__json_encoder__",
            "__json_decoder__",
            "__schema__",
            "__datasources__",
        }

        for attr in reserved_attributes:
            if attr in namespace:
                raise TypeError(f"Attribute {attr} is reserved")

        kwargs.setdefault("kw_only", True)
        kwargs.setdefault("dict", True)

        apply_entry_defaults(
            namespace=namespace, reserved_attributes=reserved_attributes
        )

        return super().__new__(cls, name, bases, namespace, **kwargs)

    def __call__(cls: type["DataModel"], *args: Any, **kwargs: Any) -> "DataModel":
        """Instantiate a DataModel from merged datasource data and explicit kwargs.

        Args:
            *args: Positional arguments (not supported).
            **kwargs: Explicit field overrides.

        Returns:
            A validated DataModel instance.

        Raises:
            TypeError: If positional arguments are provided.
        """
        if args:
            raise TypeError(
                f"Class {cls.__name__} does not support positional arguments. "
                "Use keyword arguments instead."
            )

        if cls.__datasources__ is not None and not issubclass(cls, DataSource):
            kwargs = cls.from_datasources(*cls.__datasources__, **kwargs)

        return msgspec.convert(kwargs, type=cls, from_attributes=True, str_keys=True)


class DataModel(msgspec.Struct, metaclass=DataModelMeta):
    """Base structured data container with optional datasource loading."""

    __json_encoder__: ClassVar[msgspec.json.Encoder] = get_json_encoder()
    __json_decoder__: ClassVar[msgspec.json.Decoder | None] = None
    __schema__: ClassVar[dict[str, Any] | None] = None
    __datasources__: ClassVar[tuple["DataSource", ...] | None] = None

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> Self:
        """Build an instance from a plain data mapping.

        Args:
            data: Input mapping.

        Returns:
            Validated model instance.
        """
        return msgspec.convert(data, type=cls, from_attributes=True, str_keys=True)

    @classmethod
    def from_json(cls, json_str: str | bytes) -> Self:
        """Build an instance from JSON bytes/string.

        Args:
            json_str: JSON payload.

        Returns:
            Decoded model instance.
        """
        if cls.__json_decoder__ is None:
            cls.__json_decoder__ = msgspec.json.Decoder(type=cls)
        return cls.__json_decoder__.decode(json_str)

    @classmethod
    def model_json_schema(cls, indent: int = 0) -> str:
        """Return the model JSON schema as a JSON string.

        Args:
            indent: Optional pretty-print indentation level.

        Returns:
            JSON schema string.
        """
        if cls.__schema__ is None:
            cls.__schema__ = msgspec.json.schema(cls)
        json_str = cls.__json_encoder__.encode(cls.__schema__).decode()
        if indent > 0:
            return msgspec.json.format(json_str, indent=indent)
        return json_str

    @classmethod
    def from_datasources(
        cls,
        *datasource_args: "DataSource",
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        """Load and merge data from datasources plus explicit keyword overrides.

        Datasources are evaluated left-to-right, then keyword arguments are merged
        last (highest precedence).

        Args:
            *datasource_args: Datasource instances used to load patches.
            **kwargs: Explicit field overrides.

        Returns:
            Merged mapping.

        Raises:
            TypeError: If any datasource returns a non-mapping payload.
        """
        merged_data: dict[str, Any] = {}
        for datasource in datasource_args:
            datasource_data = datasource.clone().load(model=cls)
            if not isinstance(datasource_data, Mapping):
                raise TypeError(
                    f"DataSource {datasource.__class__.__name__} returned a "
                    "non-mapping value"
                )
            deep_merge_into(merged_data, datasource_data)
        if kwargs:
            deep_merge_into(merged_data, kwargs)
        return merged_data

    def model_dump(self) -> dict[str, Any]:
        """Serialize the model into Python builtins.

        Returns:
            Dictionary representation of the instance.
        """
        return msgspec.to_builtins(self)

    def model_dump_json(self, indent: int = 0) -> str:
        """Serialize the model to a JSON string.

        Args:
            indent: Optional pretty-print indentation level.

        Returns:
            JSON string representation.
        """
        json_str = self.__json_encoder__.encode(self)
        if indent > 0:
            return msgspec.json.format(json_str, indent=indent)
        return json_str.decode()


class DataSource(DataModel):
    """Base class for data-producing sources."""

    def load(self, model: type[DataModel] | None = None) -> dict[str, Any]:
        """Load data from the source.

        Args:
            model: Optional target model requesting data.

        Returns:
            Mapping patch to merge into model input data.
        """
        raise NotImplementedError

    def clone(self) -> Self:
        """Clone datasource configuration to avoid shared mutable state.

        Returns:
            Deep-cloned datasource instance.
        """
        return copy.deepcopy(self)


def datasources(*datasource_args: DataSource):
    """Class decorator that binds datasource templates to a DataModel class.

    Args:
        *datasource_args: Datasource templates evaluated on model construction.

    Returns:
        Decorator that stores cloned datasource templates on the class.
    """

    def decorator(cls: type[DataModel]) -> type[DataModel]:
        """Attach datasource templates to the decorated class.

        Args:
            cls: Model class being decorated.

        Returns:
            Same class with datasource templates attached.
        """
        if datasource_args:
            cls.__datasources__ = tuple(
                datasource.clone() for datasource in datasource_args
            )
        return cls

    return decorator
