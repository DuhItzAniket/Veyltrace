"""Network, AI and ground-truth isolation of the engines (02 §9; AGENTS §4.3 and §4.5).

Why: engines 1–7 and 9 must stay offline and deterministic, and no engine may see ground truth.
Three independent checks enforce this, so one blind spot never lets a leak through:

1. Fresh interpreter (`python -I`), baseline rule (M0 lead decision 2026-11-06, replacing D-22):
   a baseline interpreter imports only pyarrow (with pyarrow.parquet, which every engine reads its
   tables through), numpy, pyyaml and veyltrace_contracts and defines one pydantic model; every
   entry-point target of an engine distribution (every `veyltrace.*`
   group except `veyltrace.fetchers`) is then imported in a fresh interpreter on top of that
   baseline. A deny-listed module that the target loads and the baseline did not load fails.
   `socket` is therefore tolerated exactly when the baseline already loads it (pyarrow and pydantic
   do), while `ssl`, `http.client`, `asyncio`, … are not. One documented exception: on Linux the
   pyarrow wheel's `pyarrow.fs` (imported by pyarrow.parquet) loads `ssl`, so the baseline may load
   the modules in `BASELINE_TOLERATED` and nothing else from the deny-list. To compensate, engine and
   core source may not import pyarrow's network-capable modules (`PYARROW_NETWORK`) nor write a
   remote-filesystem URI (`REMOTE_FS_LITERALS`). Fetcher targets keep their own check:
   they may load `urllib.request` (and what it pulls in), nothing else from the deny-list.
2. AST scan of engine and core source (tests excluded): banned imports (`socket`, the deny-list,
   `importlib.metadata`, `veyltrace_core.synth` / `.testing`, torch/transformers outside
   `veyltrace_anomara/tsfm/`), `duckdb.connect` outside `veyltrace_core.duck`, and every
   third-party import checked against the package's `[tool.veyltrace.isolation] allow` list in its
   own pyproject.toml (M0 lead decision 2026-11-06; the lead's deny-list below always wins).
3. Literal scan (docstrings skipped): path literals that point at ground truth (`bench/`, `lab/`,
   `answer_key`, `inject_time`) and the alert hint field `t_alert_hint_ns` outside the modules
   allowed to name them.

`VEYLTRACE_CHECK_PACKAGE=<name>` restricts the parametrised tests to one package; scripts/check.py
sets it for `--package <name>`.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from importlib.metadata import Distribution, distribution
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = ROOT / "packages"
PACKAGE_FILTER_ENV = "VEYLTRACE_CHECK_PACKAGE"

# The ten engines in pipeline order (AGENTS §1).
ENGINES = (
    "infralume",
    "signalyth",
    "anomara",
    "causync",
    "causalith",
    "faultloom",
    "causatrix",
    "relentra",
    "causentra",
    "causivra",
)
# Only these may import veyltrace_llm (AGENTS §4.3); the gateway is not an engine.
LLM_PACKAGES = frozenset({"relentra", "causivra", "gateway"})
LLM_MODULE = "veyltrace_llm"
# Packages whose source is scanned: core (shared kernel loaded into every engine), the engines and
# the gateway (literal allow-list and its own bans). llm, bench and lab are out of scope by design.
SCANNED = ("core", *ENGINES, "gateway")

# --- lead-owned lists (M0 lead decision 2026-11-06 §2.2; check_ci §3.1) ------------------------
#: sys.modules deny-list, for modules the baseline interpreter does not already load. Prefix match.
DENY_MODULES: tuple[str, ...] = (
    "ssl",
    "http.client",
    "http.server",
    "urllib.request",
    "asyncio",
    "socketserver",
    "ftplib",
    "smtplib",
    "xmlrpc",
    "grpc",
    "requests",
    "httpx",
    "httpcore",
    "h11",
    "aiohttp",
    "urllib3",
    "websockets",
    "fastapi",
    "starlette",
    "uvicorn",
    "veyltrace_llm",
    "veyltrace_gateway",
    "anthropic",
    "openai",
    "ollama",
    "litellm",
    "boto3",
    "botocore",
    "torch",
    "transformers",
    "huggingface_hub",
    # check_ci §3.1: the dataset fetcher is never reachable from an engine's import graph.
    "veyltrace_infralume.fetch",
)
#: Extra modules banned from engine and core-engine-facing *source* (not a sys.modules rule, because
#: the baseline already loads them): raw sockets, and importlib.metadata, which loads socket and
#: makes outputs depend on installed versions (critic gaps: ALGO_VERSION instead).
AST_EXTRA_BANNED: tuple[str, ...] = ("socket", "importlib.metadata")
#: Deny-listed modules the baseline interpreter may load, each with the reason. Keep it minimal: a
#: new entry is a lead decision. Found by CI run 42467001795 (ubuntu-latest), not on Windows.
BASELINE_TOLERATED: Mapping[str, str] = {
    "ssl": "pyarrow.parquet imports pyarrow.fs; the Linux pyarrow wheel's pyarrow._fs loads ssl "
    "for its S3/GCS TLS setup (the Windows wheel does not)",
}
#: pyarrow modules that can reach the network (remote filesystems, Arrow Flight). The baseline loads
#: some of them through pyarrow.parquet, so the sys.modules rule cannot see them; engine and core
#: source must never import them (AST rule, compensating control for BASELINE_TOLERATED).
PYARROW_NETWORK: tuple[str, ...] = (
    "pyarrow.fs",
    "pyarrow._fs",
    "pyarrow._s3fs",
    "pyarrow._gcsfs",
    "pyarrow._azurefs",
    "pyarrow._hdfs",
    "pyarrow.flight",
    "pyarrow._flight",
)
#: Remote-filesystem URI schemes pyarrow.parquet would resolve through pyarrow.fs on its own: engine
#: and core source never write one (literal rule, same compensating control).
REMOTE_FS_LITERALS: tuple[str, ...] = ("s3://", "gs://", "gcs://", "hdfs://", "abfs://", "abfss://")
#: Test-only and ground-truth-bearing core modules: engines never import them (critic gap: the
#: synth generator encodes the synth ground truth).
CORE_PRIVATE = ("veyltrace_core.synth", "veyltrace_core.testing")
#: Package-specific bans that hold whatever the package's allow-list says (check_ci §3.3).
PACKAGE_DENY: Mapping[str, tuple[str, ...]] = {
    "core": ("pandas",),
    "signalyth": ("drain3.redis_persistence", "drain3.kafka_persistence"),
    "causalith": ("veyltrace_anomara",),
    "faultloom": ("pandas", "tokenizers"),
    "causatrix": ("pandas",),
    "causentra": ("pandas",),
    "relentra": ("veyltrace_causentra",),
    "gateway": ("kubernetes", "docker"),
}
#: Import-time only: Relentra's api never loads its baseline module (check_ci §3.3).
TARGET_DENY: Mapping[str, tuple[str, ...]] = {"relentra": ("veyltrace_relentra.baseline",)}
#: Third-party imports core may use (packages/core/AGENTS.md "Allowed deps"; pydantic, referencing
#: and click come with the generated models, jsonschema and typer).
CORE_BASE_ALLOW = (
    "numpy",
    "pyarrow",
    "duckdb",
    "yaml",
    "jsonschema",
    "referencing",
    "typer",
    "click",
    "pydantic",
)
#: Core modules that may import importlib.metadata: engines never import them (core_api_spec §0).
CORE_METADATA_MODULES = ("veyltrace_core.plugins", "veyltrace_core.pipeline", "veyltrace_core.cli")
#: Core modules never imported by an engine process at import time; skipped by the fresh-interpreter
#: core check (cli pulls in typer/click; testing is test-only).
CORE_NOT_ENGINE_FACING = ("veyltrace_core.cli", "veyltrace_core.testing")
#: The only call site of duckdb.connect (M0 lead decision 2026-11-06 §2.3).
DUCK_MODULE = "veyltrace_core.duck"
#: Anomara's lazy, off-by-default TSFM plugin (AGENTS §4.3; critic gap: chronos imports transformers).
TSFM_PREFIX = "veyltrace_anomara.tsfm"
TSFM_ALLOWED = ("torch", "transformers")
#: Infralume's dataset fetcher: stdlib urllib only (AGENTS §4.3).
FETCH_PREFIX = "veyltrace_infralume.fetch"
FETCH_ALLOWED = ("urllib.request",)
FETCHERS_GROUP = "veyltrace.fetchers"
GROUP_PREFIX = "veyltrace."

# --- literal scan (02 §9 rule 3; AGENTS §4.5; M0 lead decision §2.1) ---------------------------
#: Modules allowed to name the alert hint field (the lead's list: Infralume derives it, core's alert
#: step reads it, core.context redacts it, adapters and synth produce it, the gateway nulls it).
HINT_ALLOWED = (
    "veyltrace_infralume",
    "veyltrace_core.alert",
    "veyltrace_core.context",
    # The leaf module that defines the field name and the redaction io applies (D-15).
    "veyltrace_core.hint",
    "veyltrace_core.adapters",
    "veyltrace_core.synth",
    "veyltrace_core.testing",
    "veyltrace_gateway",
    # R-02 bootstrap stubs play Infralume's role (they write the stub case_manifest) until O-00.
    "veyltrace_core.stubs",
)
#: Modules allowed ground-truth path literals: Infralume's deny/allow-lists name answer_key and
#: inject_time to refuse them, synth writes answer keys, testing builds fixtures, and the CLI's help
#: text names `bench run bench/experiments/...` (it delegates to bench, never reads it).
GROUND_TRUTH_ALLOWED = (
    "veyltrace_infralume",
    "veyltrace_core.synth",
    "veyltrace_core.testing",
    "veyltrace_core.cli",
    "veyltrace_gateway",
    # Names bench/results only to exclude it from the dirty-tree digest (lead decision §2.9).
    "veyltrace_core.pipeline",
)
GROUND_TRUTH_LITERALS = ("bench/", "lab/", "answer_key", "inject_time")
#: Whole path segments that point at ground truth when they appear in a path join
#: (`ROOT / "bench" / "results"`, `Path("lab")`), the pathlib spelling of "bench/" and "lab/".
GROUND_TRUTH_SEGMENTS = {"bench": "bench/", "lab": "lab/"}
HINT_LITERAL = "t_alert_hint_ns"
#: The unredacted case_manifest readers and the RunContext capability carry this word
#: (veyltrace_core.hint); naming them outside the allow-list is naming the hint (D-15).
UNREDACTED_TOKEN = "unredacted"
#: io defines the unredacted readers and the pipeline grants the capability to its two steps.
UNREDACTED_ALLOWED = (*HINT_ALLOWED, "veyltrace_core.io", "veyltrace_core.pipeline")
#: Calls whose string arguments are path segments.
PATH_CALLS = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "os.path.join", "path.join", "posixpath.join"}
)
PATH_METHODS = frozenset({"joinpath", "with_name"})
#: Package-only literal bans: Causentra gets calibration through ctx.config (02 §9 rule 3), and
#: Signalyth never loads change events (check_ci §3.4).
PACKAGE_LITERALS: Mapping[str, tuple[str, ...]] = {
    "causentra": ("config/calibration",),
    "signalyth": ("telemetry.events",),
}

# --- fresh-interpreter probe ------------------------------------------------------------------
#: Seconds per fresh-interpreter import; generous for a cold Windows laptop (a priori).
PROBE_TIMEOUT_S = 120
THREAD_PINS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
_PROBE = r"""
import importlib, json, sys, traceback
args = json.loads(sys.argv[1])
import numpy, pyarrow, pyarrow.parquet, yaml, veyltrace_contracts, pydantic
class _BaselineModel(pydantic.BaseModel):
    x: int
_BaselineModel(x=1)
for name in args["pre"]:
    importlib.import_module(name)
before = set(sys.modules)
error = None
if args["target"]:
    try:
        importlib.import_module(args["target"])
    except BaseException as exc:
        error = "".join(traceback.format_exception(exc))
print(json.dumps({"before": sorted(before), "new": sorted(set(sys.modules) - before), "error": error}))
"""


def _selected(names: Iterable[str]) -> list[str]:
    """Apply the VEYLTRACE_CHECK_PACKAGE filter (scripts/check.py --package)."""
    only = os.environ.get(PACKAGE_FILTER_ENV, "").strip()
    return [n for n in names if not only or n == only]


def _matches(module: str, prefixes: Iterable[str]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def _probe_env() -> dict[str, str]:
    env = dict(os.environ)
    for var in THREAD_PINS:
        env.setdefault(var, "1")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _probe(target: str | None, pre: Iterable[str] = ()) -> dict[str, object]:
    """Import `target` in a fresh isolated interpreter after the baseline (and `pre`) imports."""
    arg = json.dumps({"target": target, "pre": list(pre)})
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE, arg],
        capture_output=True,
        timeout=PROBE_TIMEOUT_S,
        env=_probe_env(),
        cwd=ROOT,
        check=False,
    )
    stdout = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not stdout:
        stderr = proc.stderr.decode("utf-8", "replace")
        pytest.fail(f"probe for {target!r} exited {proc.returncode}:\n{stderr}")
    result: dict[str, object] = json.loads(stdout.splitlines()[-1])
    return result


@cache
def _baseline() -> frozenset[str]:
    """sys.modules of the baseline interpreter (lead decision §2.2)."""
    result = _probe(None)
    before = result["before"]
    assert isinstance(before, list)
    return frozenset(str(m) for m in before)


# --- package metadata -------------------------------------------------------------------------
def _package_dir(package: str) -> Path:
    return PACKAGES_DIR / package


def _pyproject(package: str) -> dict[str, object]:
    return tomllib.loads((_package_dir(package) / "pyproject.toml").read_bytes().decode("utf-8"))


def _allow_list(package: str) -> tuple[str, ...]:
    """The package's own `[tool.veyltrace.isolation] allow` entries (dotted module prefixes)."""
    tool = _pyproject(package).get("tool", {})
    assert isinstance(tool, dict)
    section = tool.get("veyltrace", {}).get("isolation", {})
    allow = section.get("allow", [])
    if not isinstance(allow, list) or not all(isinstance(a, str) and a for a in allow):
        pytest.fail(
            f"packages/{package}/pyproject.toml: [tool.veyltrace.isolation] allow must be a list of names"
        )
    return tuple(sorted(allow))


def _module_prefix(package: str) -> str:
    return f"veyltrace_{package}"


def _deny_for(package: str) -> tuple[str, ...]:
    """The lead's sys.modules deny-list as it applies to one package."""
    deny = [d for d in DENY_MODULES if not (package in LLM_PACKAGES and d == LLM_MODULE)]
    return (*deny, *PACKAGE_DENY.get(package, ()))


def _fetcher_deny(package: str) -> tuple[str, ...]:
    """The deny-list for a `veyltrace.fetchers` target: everything but the fetcher exemption."""
    exempt = (FETCH_PREFIX, *FETCH_ALLOWED)
    return tuple(d for d in _deny_for(package) if not _matches(d, exempt))


def _dist(package: str) -> Distribution:
    return distribution(f"veyltrace-{package}")


@dataclass(frozen=True)
class Target:
    """One module to import in a fresh interpreter, with the rules that apply to it."""

    package: str
    module: str
    origin: str  # "<group>:<name>" or "core module"
    pre: tuple[str, ...]
    deny: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.package}:{self.module}"


def _targets() -> list[Target]:
    """Every entry-point target of the engine and core distributions, plus core's own modules."""
    out: dict[str, Target] = {}
    for package in ("core", *ENGINES):
        try:
            eps = _dist(package).entry_points
        except Exception:  # the distribution is not installed: reported by test_workspace
            continue
        for ep in sorted(eps, key=lambda e: (e.group, e.name)):
            if not ep.group.startswith(GROUP_PREFIX):
                continue
            module = ep.value.split(":", 1)[0].strip()
            deny = _deny_for(package)
            pre: tuple[str, ...] = ()
            if package in LLM_PACKAGES:
                pre = (LLM_MODULE,)
            if ep.group == FETCHERS_GROUP:
                # The fetcher's own check (check_ci §3.1-3.2): urllib.request and the fetcher's own
                # modules are allowed, the rest of the deny-list still applies.
                pre = FETCH_ALLOWED
                deny = _fetcher_deny(package)
            elif package != "core":
                deny = (*deny, *CORE_PRIVATE, *TARGET_DENY.get(package, ()))
            out.setdefault(module, Target(package, module, f"{ep.group}:{ep.name}", pre, deny))
    for mod in _core_modules():
        if not _matches(mod.name, CORE_NOT_ENGINE_FACING) and mod.name not in out:
            out[mod.name] = Target("core", mod.name, "core module", (), _deny_for("core"))
    return [out[k] for k in sorted(out)]


# --- source scanning --------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceModule:
    package: str
    name: str
    path: Path
    is_package: bool
    tree: ast.Module

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()


def _iter_modules(package: str) -> Iterator[SourceModule]:
    src = _package_dir(package) / "src"
    # Every .py under src/ is importable engine code, including a `tests` or `fixtures` package
    # placed there (package tests live in packages/<pkg>/tests/, outside src), so nothing is skipped.
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src)
        parts = list(rel.with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        tree = ast.parse(path.read_bytes(), filename=str(path))
        yield SourceModule(package, ".".join(parts), path, is_package, tree)


@cache
def _modules(package: str) -> tuple[SourceModule, ...]:
    return tuple(_iter_modules(package))


def _core_modules() -> tuple[SourceModule, ...]:
    return _modules("core")


def _resolve_relative(mod: SourceModule, level: int, name: str | None) -> str:
    base = mod.name.split(".") if mod.is_package else mod.name.split(".")[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([*base, *([name] if name else [])])


def _imports(mod: SourceModule) -> Iterator[tuple[int, str, tuple[str, ...]]]:
    """(line, module, imported names) for every import statement.

    `import a.b` gives ("a.b", ()); `from a import b, c` gives ("a", ("b", "c")), because `b` may be
    a submodule (`from importlib import metadata`). Relative imports are resolved against the
    module's own name. A string-literal `importlib.import_module("x")` / `__import__("x")` call,
    positional or `name="x"`, counts as `import x`.
    """
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, ()
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(mod, node.level, node.module) if node.level else (node.module or "")
            yield node.lineno, base, tuple(a.name for a in node.names if a.name != "*")
        elif isinstance(node, ast.Call) and _dotted(node.func) in DYNAMIC_IMPORTS:
            args = [*node.args[:1], *(k.value for k in node.keywords if k.arg == "name")]
            for arg in args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    yield node.lineno, arg.value, ()


#: Calls that import the module named by their first argument (or `name=` keyword).
DYNAMIC_IMPORTS = frozenset({"importlib.import_module", "import_module", "__import__"})


def _dotted(node: ast.expr) -> str:
    """'a.b.c' for a Name/Attribute chain, '' otherwise."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """ids of the Constant nodes that are module, class or function docstrings."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


def _string_literals(mod: SourceModule) -> Iterator[tuple[int, str]]:
    """Non-docstring string constants, with Windows separators turned into "/"."""
    skip = _docstring_nodes(mod.tree)
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value.replace("\\", "/")


def _identifiers(mod: SourceModule) -> Iterator[tuple[int, str]]:
    """Every name the code spells: attributes, names, keyword arguments, parameters, imported
    names and definitions (`m.t_alert_hint_ns`, `Model(t_alert_hint_ns=1)`, `from io import x`)."""
    for node in ast.walk(mod.tree):
        line: int = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute):
            yield line, node.attr
        elif isinstance(node, ast.Name):
            yield line, node.id
        elif isinstance(node, ast.keyword | ast.arg) and node.arg is not None:
            yield line, node.arg
        elif isinstance(node, ast.alias):
            yield line, node.name
            if node.asname:
                yield line, node.asname
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield line, node.name


def _path_call_args(node: ast.expr) -> list[ast.expr] | None:
    """The segment arguments of `Path(...)`, `os.path.join(...)` or `p.joinpath(...)`, else None."""
    if not isinstance(node, ast.Call):
        return None
    func = _dotted(node.func)
    method = node.func.attr if isinstance(node.func, ast.Attribute) else ""
    if func in PATH_CALLS or func.rsplit(".", 1)[-1] in PATH_CALLS or method in PATH_METHODS:
        return list(node.args)
    return None


def _div_operands(node: ast.expr) -> list[ast.expr]:
    """The flattened operands of an `a / b / c` chain, with path calls expanded to their args."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return [*_div_operands(node.left), *_div_operands(node.right)]
    args = _path_call_args(node)
    return [node] if args is None else args


def _path_joins(mod: SourceModule) -> Iterator[tuple[int, tuple[str, ...]]]:
    """(line, path segments) of every path built from string constants: `a / "bench" / "x"`,
    `Path("lab", "cases")`, `os.path.join("bench", ...)`, `p.joinpath("lab")`. Non-constant parts
    are left out, so `ROOT / "bench"` gives ("bench",)."""
    for node in ast.walk(mod.tree):
        parts: list[ast.expr] = []
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts = _div_operands(node)
        elif isinstance(node, ast.Call):
            parts = _path_call_args(node) or []
        texts = [p.value for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, str)]
        segments = tuple(seg for text in texts for seg in text.replace("\\", "/").split("/") if seg)
        if segments:
            yield getattr(node, "lineno", 0), segments


def _stdlib(module: str) -> bool:
    return module.split(".", 1)[0] in sys.stdlib_module_names


def _first_party_allowed(package: str) -> tuple[str, ...]:
    base = ["veyltrace_core", "veyltrace_contracts", _module_prefix(package)]
    if package in LLM_PACKAGES:
        base.append(LLM_MODULE)
    if package == "core":
        base.extend(CORE_BASE_ALLOW)
    return tuple(base)


def _banned_imports(package: str, module: str) -> tuple[str, ...]:
    """Modules `module` (in `package`) must never import, per the lead's rules."""
    banned: list[str] = list(PACKAGE_DENY.get(package, ()))
    if package == "gateway":
        return tuple(banned)  # a server: network allowed, only its own bans (check_ci §3.3)
    banned.extend(_deny_for(package))
    banned.append("socket")
    banned.extend(PYARROW_NETWORK)
    if not (package == "core" and _matches(module, CORE_METADATA_MODULES)):
        banned.append("importlib.metadata")
    if package != "core":
        # They load importlib.metadata and subprocess (git): engines never import them (§0).
        banned.extend(CORE_METADATA_MODULES)
    if not _matches(module, CORE_PRIVATE):
        banned.extend(CORE_PRIVATE)
    if _matches(module, (TSFM_PREFIX,)):
        banned = [b for b in banned if b not in TSFM_ALLOWED]
    if _matches(module, (FETCH_PREFIX,)):
        banned = [b for b in banned if b not in (*FETCH_ALLOWED, FETCH_PREFIX)]
    return tuple(banned)


def _module_import_problems(package: str, mod: SourceModule, allowed: tuple[str, ...]) -> list[str]:
    """Banned imports and imports outside `allowed` in one module."""
    problems: list[str] = []
    banned = _banned_imports(package, mod.name)
    for line, base, names in _imports(mod):
        candidates = [base, *(f"{base}.{n}" for n in names)]
        hits = [c for c in candidates if c and _matches(c, banned)]
        if hits:
            problems.extend(f"{mod.rel}:{line}: banned import {c!r}" for c in hits)
            continue
        if not base or _stdlib(base) or _matches(base, allowed):
            continue
        # `from veyltrace_causalith import entry` passes with allow "veyltrace_causalith.entry".
        if names and all(_matches(f"{base}.{n}", allowed) for n in names):
            continue
        problems.append(
            f"{mod.rel}:{line}: import {base!r} is not stdlib, first-party or in "
            f"packages/{package}/pyproject.toml [tool.veyltrace.isolation] allow"
        )
    return problems


def _allow_entry_deny(package: str) -> tuple[str, ...]:
    """What a package's allow-list may never name: the bans `_banned_imports` applies to its source.
    The gateway is a server (network allowed), so only its own bans hold there (check_ci §3.3)."""
    if package == "gateway":
        return PACKAGE_DENY.get(package, ())
    return (*_deny_for(package), *AST_EXTRA_BANNED)


def _import_violations(package: str) -> list[str]:
    allow = _allow_list(package)
    allowed = (*_first_party_allowed(package), *allow)
    problems: list[str] = []
    for entry in allow:
        if entry in _allow_entry_deny(package) or _matches(entry, CORE_PRIVATE):
            problems.append(
                f"packages/{package}/pyproject.toml: allow-list entry {entry!r} is on the lead's deny-list"
            )
    for mod in _modules(package):
        problems.extend(_module_import_problems(package, mod, allowed))
    return sorted(set(problems))


def _module_duckdb_problems(mod: SourceModule) -> list[str]:
    """duckdb.connect anywhere but veyltrace_core.duck (lead decision §2.3)."""
    if mod.name == DUCK_MODULE:
        return []
    problems: list[str] = []
    aliases = {"duckdb"}
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Import):
            aliases.update(a.asname or a.name for a in node.names if a.name == "duckdb")
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "duckdb"
            and any(a.name == "connect" for a in node.names)
        ):
            problems.append(
                f"{mod.rel}:{node.lineno}: `from duckdb import connect`; use {DUCK_MODULE}.connect"
            )
    for node in ast.walk(mod.tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "connect"
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        ):
            problems.append(
                f"{mod.rel}:{node.lineno}: duckdb.connect; use {DUCK_MODULE}.connect(cfg, run_dir)"
            )
    return problems


def _duckdb_connect_violations(package: str) -> list[str]:
    return sorted({p for mod in _modules(package) for p in _module_duckdb_problems(mod)})


def _module_literal_problems(package: str, mod: SourceModule) -> list[str]:
    """Ground-truth paths and the alert-hint field (as a string, an identifier or an unredacted
    reader) outside their allow-lists."""
    if package == "core" and _matches(mod.name, ("veyltrace_core.synth",)):
        return []  # check_ci §3.4: core minus core.synth
    hint_ok = _matches(mod.name, HINT_ALLOWED)
    unredacted_ok = _matches(mod.name, UNREDACTED_ALLOWED)
    truth_ok = _matches(mod.name, GROUND_TRUTH_ALLOWED)
    rules: list[tuple[str, bool]] = [(HINT_LITERAL, hint_ok), (UNREDACTED_TOKEN, unredacted_ok)]
    rules.extend((lit, truth_ok) for lit in GROUND_TRUTH_LITERALS)
    rules.extend((lit, False) for lit in PACKAGE_LITERALS.get(package, ()))
    rules.extend((lit, package == "gateway") for lit in REMOTE_FS_LITERALS)
    problems: set[str] = set()
    for line, text in _string_literals(mod):
        problems.update(
            f"{mod.rel}:{line}: string literal contains {literal!r}"
            for literal, allowed in rules
            if not allowed and literal in text.lower()
        )
    for line, name in _identifiers(mod):
        problems.update(
            f"{mod.rel}:{line}: identifier {name!r} names {literal!r}"
            for literal, allowed in rules[:2]
            if not allowed and literal in name.lower()
        )
    for line, segments in _path_joins(mod):
        joined = "/".join(segments) + "/"
        hits = {lit for lit, allowed in rules[2:] if not allowed and lit in joined.lower()}
        if not truth_ok:
            lowered = [seg.lower() for seg in segments]
            hits.update(GROUND_TRUTH_SEGMENTS[seg] for seg in lowered if seg in GROUND_TRUTH_SEGMENTS)
        problems.update(f"{mod.rel}:{line}: path join {joined!r} contains {lit!r}" for lit in hits)
    return sorted(problems)


def _literal_violations(package: str) -> list[str]:
    return sorted({p for mod in _modules(package) for p in _module_literal_problems(package, mod)})


# --- tests ------------------------------------------------------------------------------------
def test_baseline_loads_no_denied_module() -> None:
    """If a pyarrow/numpy/pydantic upgrade starts loading a denied module, the rule must be revisited."""
    hits = sorted(m for m in _baseline() if _matches(m, DENY_MODULES) and not _matches(m, BASELINE_TOLERATED))
    assert not hits, f"the baseline interpreter loads denied modules {hits}; ask the lead (decision §2.2)"


def test_baseline_tolerated_modules_stay_banned() -> None:
    """A tolerated baseline module stays on the deny-list and stays AST-banned in engine source."""
    banned = _banned_imports("signalyth", "veyltrace_signalyth.api")
    for module in BASELINE_TOLERATED:
        assert _matches(module, DENY_MODULES), module
        assert _matches(module, banned), module


def test_engine_distributions_declare_targets() -> None:
    """Every engine registers at least its veyltrace.engines entry point, so the probe covers it."""
    targets = {t.package for t in _targets() if t.origin.startswith("veyltrace.engines:")}
    missing = sorted(set(_selected(ENGINES)) - targets)
    assert not missing, f"no veyltrace.engines entry point found for {missing} (run `uv sync --all-packages`)"


@pytest.mark.parametrize("target", [t for t in _targets() if _selected([t.package])], ids=lambda t: t.id)
def test_fresh_interpreter_import(target: Target) -> None:
    """Importing the target loads no denied module beyond the baseline (lead decision §2.2)."""
    result = _probe(target.module, target.pre)
    error = result["error"]
    assert error is None, f"{target.module} ({target.origin}) failed to import:\n{error}"
    new = result["new"]
    assert isinstance(new, list)
    baseline = _baseline()
    hits = sorted(str(m) for m in new if m not in baseline and _matches(str(m), target.deny))
    assert not hits, f"{target.module} ({target.origin}) loads denied modules: {hits}"


@pytest.mark.parametrize("package", _selected(SCANNED))
def test_imports(package: str) -> None:
    """Banned imports and the per-package third-party allow-list (check_ci §3.2-3.3)."""
    problems = _import_violations(package)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("package", _selected(SCANNED))
def test_duckdb_connect_only_in_core_duck(package: str) -> None:
    """DuckDB connections come from veyltrace_core.duck.connect (threads, memory, no extensions)."""
    problems = _duckdb_connect_violations(package)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("package", _selected(SCANNED))
def test_literals(package: str) -> None:
    """No ground-truth paths or alert-hint references outside their allow-lists (02 §9; AGENTS §4.5)."""
    problems = _literal_violations(package)
    assert not problems, "\n".join(problems)


# --- self-tests: each rule catches what it claims to catch -----------------------------------
def _snippet(
    source: str, module: str = "veyltrace_signalyth.api", package: str = "signalyth"
) -> SourceModule:
    path = PACKAGES_DIR / package / "src" / (module.replace(".", "/") + ".py")
    return SourceModule(package, module, path, False, ast.parse(source))


_ENGINE_ALLOWED = ("veyltrace_core", "veyltrace_contracts", "veyltrace_signalyth", "numpy")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import socket", "banned import 'socket'"),
        ("from importlib import metadata", "banned import 'importlib.metadata'"),
        ("import importlib.metadata", "banned import 'importlib.metadata'"),
        ("import httpx", "banned import 'httpx'"),
        ("from veyltrace_core import synth", "banned import 'veyltrace_core.synth'"),
        ("from veyltrace_core.testing import golden", "banned import 'veyltrace_core.testing'"),
        ("import veyltrace_llm", "banned import 'veyltrace_llm'"),
        ("import torch", "banned import 'torch'"),
        ("import importlib\nimportlib.import_module('ssl')", "banned import 'ssl'"),
        ("import ssl", "banned import 'ssl'"),
        ("from pyarrow import fs", "banned import 'pyarrow.fs'"),
        ("import pyarrow.fs", "banned import 'pyarrow.fs'"),
        ("from pyarrow._s3fs import S3FileSystem", "banned import 'pyarrow._s3fs'"),
        ("import pyarrow.flight", "banned import 'pyarrow.flight'"),
        ("import pandas", "import 'pandas' is not stdlib, first-party or in"),
        ("from veyltrace_causalith import graph", "import 'veyltrace_causalith' is not stdlib"),
    ],
)
def test_import_rules_catch(source: str, expected: str) -> None:
    problems = _module_import_problems("signalyth", _snippet(source), _ENGINE_ALLOWED)
    assert any(expected in p for p in problems), problems


@pytest.mark.parametrize(
    "source",
    [
        "import json, os\nfrom pathlib import Path",
        "import numpy as np",
        "from veyltrace_core import io",
        "from . import api",
        "from __future__ import annotations",
    ],
)
def test_import_rules_allow(source: str) -> None:
    assert _module_import_problems("signalyth", _snippet(source), _ENGINE_ALLOWED) == []


def test_import_exemptions_are_scoped() -> None:
    allowed = (*_ENGINE_ALLOWED, "veyltrace_causalith.entry")
    entry = _snippet("from veyltrace_causalith import entry")
    assert _module_import_problems("signalyth", entry, allowed) == []
    tsfm = _snippet("import torch", "veyltrace_anomara.tsfm.chronos", "anomara")
    assert _module_import_problems("anomara", tsfm, ("torch",)) == []
    fetch = _snippet("import urllib.request", "veyltrace_infralume.fetch.hf", "infralume")
    assert _module_import_problems("infralume", fetch, _first_party_allowed("infralume")) == []
    api = _snippet("import urllib.request", "veyltrace_infralume.api", "infralume")
    assert _module_import_problems("infralume", api, _first_party_allowed("infralume")) != []
    llm = _snippet("import veyltrace_llm", "veyltrace_relentra.api", "relentra")
    assert _module_import_problems("relentra", llm, _first_party_allowed("relentra")) == []
    meta = _snippet("import importlib.metadata", "veyltrace_core.plugins", "core")
    assert _module_import_problems("core", meta, _first_party_allowed("core")) == []
    meta_io = _snippet("import importlib.metadata", "veyltrace_core.io", "core")
    assert _module_import_problems("core", meta_io, _first_party_allowed("core")) != []


def test_duckdb_rule() -> None:
    assert _module_duckdb_problems(_snippet("import duckdb\ncon = duckdb.connect()")) != []
    assert _module_duckdb_problems(_snippet("import duckdb as d\ncon = d.connect()")) != []
    assert _module_duckdb_problems(_snippet("from duckdb import connect")) != []
    assert _module_duckdb_problems(_snippet("import duckdb\nduckdb.connect()", DUCK_MODULE, "core")) == []


def test_literal_rule_skips_docstrings() -> None:
    doc = '"""Reads nothing under bench/ or t_alert_hint_ns."""\nX = 1'
    assert _module_literal_problems("signalyth", _snippet(doc)) == []
    code = 'P = "bench/results"\nQ = "t_alert_hint_ns"\nR = "telemetry.events"'
    found = _module_literal_problems("signalyth", _snippet(code))
    assert len(found) == 3, found
    hint = _snippet('Q = "t_alert_hint_ns"', "veyltrace_core.alert", "core")
    assert _module_literal_problems("core", hint) == []


@pytest.mark.parametrize(
    "source",
    [
        "x = m.t_alert_hint_ns",
        "z = M(t_alert_hint_ns=1)",
        'y = getattr(m, "t_alert" "_hint_ns")',
        "def f(t_alert_hint_ns: int) -> int:\n    return t_alert_hint_ns",
        "from veyltrace_core import io\nm = io.read_unredacted('case_manifest', d)",
        "from veyltrace_core.io import read_path_unredacted",
        "from dataclasses import replace\nc = replace(ctx, step='infralume', unredacted_hint=True)",
        "c = replace(ctx, **{'unredacted_hint': True})",
    ],
)
def test_hint_rule_catches_identifiers(source: str) -> None:
    """The hint is caught as an attribute, keyword, name or unredacted reader, not only as a string."""
    assert _module_literal_problems("signalyth", _snippet(source)) != []


def test_hint_rule_allows_core_readers() -> None:
    ctx = _snippet("v = io.read_unredacted('case_manifest', d)", "veyltrace_core.context", "core")
    assert _module_literal_problems("core", ctx) == []
    grant = _snippet("RunContext(unredacted_hint=True)", "veyltrace_core.pipeline", "core")
    assert _module_literal_problems("core", grant) == []


@pytest.mark.parametrize(
    ("source", "package"),
    [
        ('P = Path(__file__).parents[4] / "bench" / "results"', "signalyth"),
        ('P = Path("lab") / "cases"', "signalyth"),
        (r'P = "bench\\results"', "signalyth"),
        ('P = os.path.join("lab", "x")', "signalyth"),
        ('P = root.joinpath("bench", "results")', "signalyth"),
        ('P = Path("config") / "calibration"', "causentra"),
        (r'P = "config\\calibration"', "causentra"),
    ],
)
def test_ground_truth_rule_catches_path_spellings(source: str, package: str) -> None:
    module = f"veyltrace_{package}.api"
    assert _module_literal_problems(package, _snippet(source, module, package)) != []


def test_ground_truth_rule_allows_plain_words() -> None:
    assert _module_literal_problems("signalyth", _snippet('ROOTS = frozenset({"bench", "lab"})')) == []
    allowed = _snippet('P = ROOT / "bench" / "results"', "veyltrace_core.pipeline", "core")
    assert _module_literal_problems("core", allowed) == []


def test_import_rules_catch_keyword_and_core_runner_modules() -> None:
    kw = _snippet("import importlib\nimportlib.import_module(name='ssl')")
    assert any("'ssl'" in p for p in _module_import_problems("signalyth", kw, _ENGINE_ALLOWED))
    for module in CORE_METADATA_MODULES:
        source = f"from {module.rsplit('.', 1)[0]} import {module.rsplit('.', 1)[1]}"
        found = _module_import_problems("signalyth", _snippet(source), _ENGINE_ALLOWED)
        assert any(module in p for p in found), (module, found)


def test_fetcher_targets_allow_their_own_modules() -> None:
    deny = _fetcher_deny("infralume")
    assert not _matches("veyltrace_infralume.fetch.rcaeval", deny)
    assert not _matches("urllib.request", deny)
    assert _matches("ssl", deny) and _matches("veyltrace_llm", deny)
    assert _matches("veyltrace_infralume.fetch.rcaeval", _deny_for("infralume"))


def test_allow_list_entries_follow_the_package_bans() -> None:
    """The gateway may allow-list its server stack; every other package still may not (#98)."""
    assert {"fastapi", "starlette", "uvicorn"}.isdisjoint(_allow_entry_deny("gateway"))
    assert {"kubernetes", "docker"} <= set(_allow_entry_deny("gateway"))
    for package in ("anomara", "core", "relentra"):
        assert {"fastapi", "uvicorn", "ssl", "socket"} <= set(_allow_entry_deny(package)), package


def test_modules_under_src_tests_are_scanned() -> None:
    """A `tests`/`fixtures` package inside src/ is importable engine code, so it is scanned."""
    names = [m.name for m in _modules("core")]
    src = PACKAGES_DIR / "core" / "src"
    assert len(names) == len(list(src.rglob("*.py")))


@pytest.mark.parametrize("uri", REMOTE_FS_LITERALS)
def test_remote_fs_literals_are_banned_outside_gateway(uri: str) -> None:
    """pyarrow.parquet resolves remote URIs through pyarrow.fs, so engines never write one."""
    source = f'PATH = "{uri}bucket/table.parquet"'
    assert _module_literal_problems("signalyth", _snippet(source)) != []
    gateway = _snippet(source, "veyltrace_gateway.app", "gateway")
    assert _module_literal_problems("gateway", gateway) == []
