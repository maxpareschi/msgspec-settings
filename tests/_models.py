"""Shared model fixtures used by source and helper tests."""

from typing import Literal

import msgspec


class LogModel(msgspec.Struct, kw_only=True):
    """Nested logging configuration fixture."""

    level: str = "INFO"
    file_path: str = "/var/log/app.log"


class ServerModel(msgspec.Struct, kw_only=True):
    """Server configuration fixture with nested log config."""

    host: str = "localhost"
    port: int = 8080
    log: LogModel = msgspec.field(default_factory=LogModel)


class SimpleModel(msgspec.Struct, kw_only=True):
    """Flat configuration fixture."""

    host: str = "localhost"
    port: int = 8080
    debug: bool = False


class LiteralModel(msgspec.Struct, kw_only=True):
    """Model fixture using string Literal."""

    level: Literal["DEBUG", "INFO"] = "INFO"


class IntLiteralModel(msgspec.Struct, kw_only=True):
    """Model fixture using int Literal."""

    value: Literal[1, 2] = 1


class BoolLiteralModel(msgspec.Struct, kw_only=True):
    """Model fixture using bool Literal."""

    enabled: Literal[True, False] = False


class UnionModel(msgspec.Struct, kw_only=True):
    """Model fixture using a primitive union."""

    value: int | str = 0


class OptionalNestedModel(msgspec.Struct, kw_only=True):
    """Model fixture with an optional nested Struct field."""

    log: LogModel | None = None


class AliasLogModel(msgspec.Struct, kw_only=True):
    """Nested model fixture using encoded/alias field names."""

    level: str = msgspec.field(default="INFO", name="LEVEL")
    file_path: str = msgspec.field(default="/var/log/app.log", name="FILE_PATH")


class AliasServerModel(msgspec.Struct, kw_only=True):
    """Server fixture with top-level and nested encoded field names."""

    host: str = msgspec.field(default="localhost", name="HOST")
    port: int = msgspec.field(default=8080, name="PORT")
    log: AliasLogModel = msgspec.field(default_factory=AliasLogModel, name="LOG")
