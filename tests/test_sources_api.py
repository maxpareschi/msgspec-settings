"""Tests for API datasource behavior."""

from urllib.error import URLError

import msgspec
import pytest

from msgspec_settings import APISource


class _FakeResponse:
    """Small context-manager response stub for urlopen monkeypatching."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        """Return mocked body bytes."""
        return self.payload

    def __enter__(self) -> "_FakeResponse":
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        """Exit context manager without suppressing exceptions."""
        return False


def test_empty_url_returns_empty() -> None:
    """Unset URL should be treated as absent source."""
    assert APISource().load() == {}


def test_load_valid_api_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid endpoint JSON should decode into a mapping."""

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        assert timeout == 5.0
        assert getattr(request, "full_url") == "https://example.test/config"
        return _FakeResponse(b'{"host":"api.example.com","port":9000}')

    monkeypatch.setattr("msgspec_settings.sources.api.urlopen", fake_urlopen)

    data = APISource(api_url="https://example.test/config", timeout_seconds=5.0).load()
    assert data["host"] == "api.example.com"
    assert data["port"] == 9000


def test_optional_header_is_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured header should be attached to the outgoing request."""
    captured_headers: dict[str, str] = {}

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        for key, value in request.header_items():  # type: ignore[attr-defined]
            captured_headers[key.lower()] = value
        return _FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("msgspec_settings.sources.api.urlopen", fake_urlopen)

    APISource(
        api_url="https://example.test/config",
        header_name="Authorization",
        header_value="Bearer token",
    ).load()

    assert captured_headers["authorization"] == "Bearer token"


def test_header_name_or_value_alone_raises() -> None:
    """Header name/value must be configured together."""
    with pytest.raises(ValueError, match="header_name and header_value"):
        APISource(api_url="https://example.test", header_name="Authorization").load()

    with pytest.raises(ValueError, match="header_name and header_value"):
        APISource(api_url="https://example.test", header_value="Bearer token").load()


def test_root_node_unwraps_response_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured root node should unwrap wrapped endpoint payloads."""

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(b'{"data":{"host":"wrapped.example.com","port":7000}}')

    monkeypatch.setattr("msgspec_settings.sources.api.urlopen", fake_urlopen)

    data = APISource(
        api_url="https://example.test/config",
        root_node="data",
    ).load()

    assert data["host"] == "wrapped.example.com"
    assert data["port"] == 7000


def test_missing_root_node_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing root node should yield empty mapping."""

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(b'{"meta":{"ok":true}}')

    monkeypatch.setattr("msgspec_settings.sources.api.urlopen", fake_urlopen)

    assert (
        APISource(api_url="https://example.test/config", root_node="data").load() == {}
    )


def test_failed_request_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Request failures should surface as RuntimeError with endpoint context."""

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        raise URLError("boom")

    monkeypatch.setattr("msgspec_settings.sources.api.urlopen", fake_urlopen)

    src = APISource(api_url="https://example.test/config")
    with pytest.raises(RuntimeError, match="Failed to fetch API endpoint"):
        src.load()


def test_invalid_json_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON parse failures should surface as RuntimeError with endpoint context."""

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"{broken")

    monkeypatch.setattr("msgspec_settings.sources.api.urlopen", fake_urlopen)

    src = APISource(api_url="https://example.test/config")
    with pytest.raises(RuntimeError, match="Failed to parse API response JSON"):
        src.load()


def test_unmapped_api_keys_are_stored_on_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown API keys should be split out into source unmapped runtime state."""

    class Log(msgspec.Struct, kw_only=True):
        level: str = "INFO"

    class Model(msgspec.Struct, kw_only=True):
        host: str = "localhost"
        log: Log = msgspec.field(default_factory=Log)

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(
            b'{"host":"api.example.com","unknown":1,"log":{"level":"DEBUG","levle":"typo"}}'
        )

    monkeypatch.setattr("msgspec_settings.sources.api.urlopen", fake_urlopen)

    src = APISource(api_url="https://example.test/config")
    data = src.resolve(model=Model)

    assert data == {"host": "api.example.com", "log": {"level": "DEBUG"}}
    assert src.__unmapped_kwargs__ == {"unknown": 1, "log": {"levle": "typo"}}
