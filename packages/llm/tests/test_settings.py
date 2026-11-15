"""config/llm.yaml settings and the localhost guard (08 §4, §5.4; package rule 2)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import repo_root
from veyltrace_llm.guard import ALLOW_REMOTE_ENV, check_base_url
from veyltrace_llm.settings import settings_from


def _thaw(value: Any) -> Any:
    """A mutable copy of a frozen config tree."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in cast(Mapping[str, Any], value).items()}
    if isinstance(value, list | tuple):
        return [_thaw(v) for v in cast(list[Any], value)]
    return value


def _section() -> dict[str, Any]:
    return _thaw(load_section_file("llm", config_dir=repo_root() / "config"))


def test_repo_config_is_valid() -> None:
    s = settings_from(_section(), env={})
    assert s.provider == "ollama" and s.model.name == "qwen3.5:9b" and s.model.gguf_sha256 is None
    assert (s.endpoint.host, s.endpoint.port, s.endpoint.path) == ("127.0.0.1", 11434, "")
    assert s.num_ctx == 16384 and s.num_thread is None and s.parallel == 1 and s.cache_prompt is False
    assert (s.connect_timeout_s, s.timeout_s) == (5.0, 240.0)
    assert "api_key" not in s.audit() and s.audit()["base_url"] == "http://127.0.0.1:11434"


@pytest.mark.parametrize(
    ("dotted", "value"),
    [
        ("provider", "vllm"),
        ("base_url", "ftp://127.0.0.1"),
        ("model.name", ""),
        ("model.gguf_sha256", "ABC"),
        ("runtime.num_ctx", 0),
        ("runtime.num_thread", 1.5),
        ("runtime.parallel", True),
        ("runtime.cache_prompt", "no"),
        ("request.connect_timeout_s", 0),
        ("request.timeout_s", "240"),
        ("cassette.strict", False),
    ],
)
def test_bad_values_are_config_errors(dotted: str, value: object) -> None:
    section = _section()
    node = section
    *parents, last = dotted.split(".")
    for part in parents:
        node = node[part]
    node[last] = value
    with pytest.raises(ConfigError):
        settings_from(section, env={})


def test_missing_key_is_a_config_error() -> None:
    section = _section()
    del section["request"]["timeout_s"]
    with pytest.raises(ConfigError, match=r"request\.timeout_s"):
        settings_from(section, env={})


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://LOCALHOST",
        "http://127.0.0.1:8080/v1/",
        "https://[::1]:8443",
        "http://[::1]",
    ],
)
def test_loopback_urls_pass(url: str) -> None:
    endpoint = check_base_url(url, env={})
    assert endpoint.host in {"localhost", "127.0.0.1", "::1"}
    assert not endpoint.path.endswith("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:11434",
        "http://127.0.0.2:11434",  # loopback range, but rule 2 names exactly three hosts
        "http://localhost.evil.example",
        "http://ollama:11434",
        "http://user:pw@127.0.0.1",
        "http://127.0.0.1/?q=1",
        "127.0.0.1:11434",
        "http://127.0.0.1:99999",
    ],
)
def test_remote_or_malformed_urls_are_refused(url: str) -> None:
    with pytest.raises(ConfigError):
        check_base_url(url, env={})


def test_remote_url_needs_the_opt_in() -> None:
    url = "http://192.168.1.10:11434"
    with pytest.raises(ConfigError, match=ALLOW_REMOTE_ENV):
        check_base_url(url, env={ALLOW_REMOTE_ENV: "true"})
    assert check_base_url(url, env={ALLOW_REMOTE_ENV: "1"}).host == "192.168.1.10"


def test_endpoint_url_formats_ipv6() -> None:
    assert check_base_url("http://[::1]:8080/v1", env={}).url("/chat") == "http://[::1]:8080/v1/chat"
