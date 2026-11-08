"""Determinism lint: no clock, entropy or unordered iteration in analysis code (02 §9; AGENTS §4.4).

Why: the determinism gate (`scripts/check.py --determinism`) only catches non-determinism that two
runs on one machine happen to expose. A wall-clock read, an unseeded draw, `hash()` (salted by
PYTHONHASHSEED) or a directory listing in file-system order can stay invisible there and still
change outputs on another laptop or OS. This AST scan rejects those constructs outright.

Scope: core and the ten engines, every `.py` under `src/` (package tests live outside src/;
critic gap, M0 lead decision 2026-11-06). Out of scope by design: veyltrace_llm (its monotonic clock), the
gateway, lab and bench (check_ci §3.5).

Exemptions, each with its reason:
- `time.perf_counter` / `perf_counter_ns` only in `veyltrace_core.pipeline`, for RunSummary.wall_ms,
  which is never written to an artefact (lead decision §2.12).
- builtin `hash()` only inside `__hash__` methods (in-process lookups, never an output).
- `time.sleep` only in `veyltrace_core.textio` (atomic-replace retry backoff) and
  `veyltrace_core.locks` (lock waits); sleeping never produces a value.
- `numpy.random` only in `veyltrace_core.rng`, the one seeded source (AGENTS §4.4).
- `os.environ` / `os.getenv` reads are banned in engines (Causivra exempt: receipt signing key
  location, check_ci §3.5) and in core's engine-facing modules; core's config (data_root), CLI,
  pipeline, plugins, synth and testing may read the environment.
- `os.getpid` is banned in engines; core uses it for temp-file and lock names only.

`VEYLTRACE_CHECK_PACKAGE=<name>` restricts the tests to one package (scripts/check.py --package).
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = ROOT / "packages"
PACKAGE_FILTER_ENV = "VEYLTRACE_CHECK_PACKAGE"

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
LINTED = ("core", *ENGINES)

#: Modules whose import alone is a violation: unseeded entropy sources.
BANNED_MODULES = ("random", "secrets")
#: time-module functions that read a clock (time.sleep is handled separately).
CLOCK_FUNCTIONS = frozenset(
    {
        "time",
        "time_ns",
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "perf_counter_ns",
        "process_time",
        "process_time_ns",
        "thread_time",
        "thread_time_ns",
        "localtime",
        "gmtime",
        "ctime",
        "asctime",
        "strftime",
        "clock_gettime",
        "clock_gettime_ns",
    }
)
PERF_COUNTER = frozenset({"perf_counter", "perf_counter_ns"})
PERF_COUNTER_MODULES = ("veyltrace_core.pipeline",)
SLEEP_MODULES = ("veyltrace_core.textio", "veyltrace_core.locks")
#: datetime/date constructors that read the clock.
DATETIME_NOW = frozenset({"now", "utcnow", "today"})
DATETIME_CLASSES = frozenset({"datetime", "date"})
RNG_MODULES = ("veyltrace_core.rng",)
#: Entropy calls on otherwise allowed modules.
ENTROPY_CALLS = frozenset({"uuid.uuid1", "uuid.uuid4", "os.urandom", "os.getrandom"})
#: Core modules that may read the process environment (see the module docstring).
CORE_ENV_MODULES = (
    "veyltrace_core.config",
    "veyltrace_core.cli",
    "veyltrace_core.pipeline",
    "veyltrace_core.plugins",
    "veyltrace_core.synth",
    "veyltrace_core.testing",
)
ENV_EXEMPT_PACKAGES = frozenset({"causivra"})
ENV_READS = ("os.environ", "os.environb", "os.getenv", "os.getenvb")
#: Directory listings whose order is the file system's: they must feed sorted() (or an
#: order-free consumer) directly.
LISTING_FUNCTIONS = frozenset({"os.listdir", "os.scandir", "glob.glob", "glob.iglob"})
LISTING_METHODS = frozenset({"iterdir", "glob", "rglob"})
ORDER_FREE_CONSUMERS = frozenset({"sorted", "any", "all", "set", "frozenset", "len"})
#: `for root, dirs, files in os.walk(...)`.
WALK_TUPLE_LEN = 3
#: Glob matchers that follow os.path.normcase, i.e. are case-insensitive on Windows only
#: (lead decision §2.12: fnmatch.fnmatchcase everywhere).
CASE_FOLDING_MATCHERS = frozenset({"fnmatch.fnmatch", "fnmatch.filter"})
#: Calls whose result keeps the iteration order of their argument: a set there is hash order.
ORDER_KEEPING_CALLS = frozenset({"list", "tuple", "enumerate", "iter", "next", "reversed", "map", "filter"})
ORDER_KEEPING_METHODS = frozenset({"join", "fromkeys", "extend"})
_GLOB_CHARS = frozenset("*?[")


@dataclass(frozen=True)
class SourceModule:
    package: str
    name: str
    path: Path
    tree: ast.Module

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()


def _selected(names: Iterable[str]) -> list[str]:
    only = os.environ.get(PACKAGE_FILTER_ENV, "").strip()
    return [n for n in names if not only or n == only]


def _matches(module: str, prefixes: Iterable[str]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


@cache
def _modules(package: str) -> tuple[SourceModule, ...]:
    src = PACKAGES_DIR / package / "src"
    out: list[SourceModule] = []
    # Every .py under src/ is importable code, a `tests` or `fixtures` package there included.
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        out.append(
            SourceModule(package, ".".join(parts), path, ast.parse(path.read_bytes(), filename=str(path)))
        )
    return tuple(out)


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Local name -> fully qualified name, from every import in the module (any scope)."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    top = alias.name.split(".", 1)[0]
                    names[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _qualified(node: ast.expr, aliases: dict[str, str]) -> str:
    """The fully qualified dotted name of a Name/Attribute chain, resolving import aliases."""
    dotted = _dotted(node)
    if not dotted:
        return ""
    head, _, rest = dotted.partition(".")
    base = aliases.get(head, head)
    return f"{base}.{rest}" if rest else base


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _feeds_order_free_consumer(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """True if `node` is passed (directly or as a comprehension source) to sorted()/any()/..."""
    current = node
    parent = parents.get(id(current))
    while isinstance(parent, ast.comprehension) and parent.iter is current:
        comp = parents.get(id(parent))
        if comp is None:
            return False
        current, parent = comp, parents.get(id(comp))
    return (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id in ORDER_FREE_CONSUMERS
        and current in parent.args
    )


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> str | None:
    """Name of the innermost function containing `node`, if any.

    hash() inside `__hash__` only serves in-process dict/set lookups, so it is allowed there.
    """
    parent = parents.get(id(node))
    while parent is not None:
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            return parent.name
        parent = parents.get(id(parent))
    return None


def _sorted_walk(call: ast.Call, parents: dict[int, ast.AST]) -> bool:
    """True for `for root, dirs, files in os.walk(...)` that fixes its order.

    The loop must sort `dirs` in place (`dirs.sort()` or `dirs[:] = sorted(...)`), which fixes the
    traversal order, and may use `files` only through sorted()/any()/... (order-free consumers).
    """
    loop = parents.get(id(call))
    if not (isinstance(loop, ast.For) and loop.iter is call and isinstance(loop.target, ast.Tuple)):
        return False
    names = [t.id if isinstance(t, ast.Name) else "" for t in loop.target.elts]
    if len(names) != WALK_TUPLE_LEN or not names[1] or not names[2]:
        return False
    dirs, files = names[1], names[2]
    sorts_dirs = False
    files_ok = True
    for stmt in loop.body:
        for node in ast.walk(stmt):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "sort"
                and _dotted(node.func.value) == dirs
            ):
                sorts_dirs = True
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Subscript) and _dotted(t.value) == dirs for t in node.targets)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "sorted"
            ):
                sorts_dirs = True
            if isinstance(node, ast.Name) and node.id == files and isinstance(node.ctx, ast.Load):
                files_ok = files_ok and _feeds_order_free_consumer(node, parents)
    return sorts_dirs and files_ok


def _is_set_expr(node: ast.expr) -> bool:
    if isinstance(node, ast.Set | ast.SetComp):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"set", "frozenset"}
    )


def _is_iter_of_set(node: ast.expr) -> bool:
    """`iter(<set>)`, as in next(iter({...}))."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "iter"
        and bool(node.args)
        and _is_set_expr(node.args[0])
    )


def _env_banned(mod: SourceModule) -> bool:
    if mod.package == "core":
        return not _matches(mod.name, CORE_ENV_MODULES)
    return mod.package not in ENV_EXEMPT_PACKAGES


def _imported_modules(tree: ast.Module) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.lineno, node.module
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"


def _violations(mod: SourceModule) -> Iterator[tuple[int, str]]:
    aliases = _aliases(mod.tree)
    parents = _parents(mod.tree)
    rng_ok = _matches(mod.name, RNG_MODULES)
    for line, name in _imported_modules(mod.tree):
        if _matches(name, BANNED_MODULES):
            yield line, f"imports {name!r}; use veyltrace_core.rng(case_id, purpose)"
        if not rng_ok and _matches(name, ("numpy.random",)):
            yield line, f"imports {name!r}; use veyltrace_core.rng(case_id, purpose)"
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Attribute | ast.Name) and not isinstance(
            parents.get(id(node)), ast.Attribute
        ):
            yield from _name_violations(mod, node, aliases, rng_ok)
        if isinstance(node, ast.Call):
            yield from _call_violations(mod, node, aliases, parents)
        if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension) and _is_set_expr(node.iter):
            yield node.iter.lineno, "iterates a set (hash order); iterate sorted(...) instead"


def _name_violations(
    mod: SourceModule, node: ast.Attribute | ast.Name, aliases: dict[str, str], rng_ok: bool
) -> Iterator[tuple[int, str]]:
    """Rules on a maximal Name/Attribute chain (e.g. `np.random.default_rng`, `os.environ`)."""
    qual = _qualified(node, aliases)
    if not qual:
        return
    module, _, func = qual.rpartition(".")
    perf_ok = func in PERF_COUNTER and _matches(mod.name, PERF_COUNTER_MODULES)
    if module == "time" and func in CLOCK_FUNCTIONS and not perf_ok:
        yield node.lineno, f"reads the clock ({qual})"
    if module == "time" and func == "sleep" and not _matches(mod.name, SLEEP_MODULES):
        yield node.lineno, "time.sleep in analysis code"
    if func in DATETIME_NOW and module.rpartition(".")[2] in DATETIME_CLASSES:
        yield node.lineno, f"reads the clock ({qual})"
    if not rng_ok and _matches(qual, ("numpy.random",)):
        yield node.lineno, f"uses {qual}; use veyltrace_core.rng(case_id, purpose)"
    if qual in ENTROPY_CALLS:
        yield node.lineno, f"uses entropy ({qual})"
    if _env_banned(mod) and _matches(qual, ENV_READS):
        yield node.lineno, f"reads the process environment ({qual}); take it from ctx.config"
    if mod.package != "core" and qual == "os.getpid":
        yield node.lineno, "uses os.getpid in engine code"


def _call_violations(
    mod: SourceModule, node: ast.Call, aliases: dict[str, str], parents: dict[int, ast.AST]
) -> Iterator[tuple[int, str]]:
    func = node.func
    if (
        isinstance(func, ast.Name)
        and func.id == "hash"
        and "hash" not in aliases
        and _enclosing_function(node, parents) != "__hash__"
    ):
        yield node.lineno, "builtin hash() is salted by PYTHONHASHSEED; use veyltrace_core.hashing"
    qual = _qualified(func, aliases)
    if qual == "os.walk":
        if not _sorted_walk(node, parents):
            yield node.lineno, "os.walk lists in file-system order; sort dirs in place and use sorted(files)"
        return
    if qual in CASE_FOLDING_MATCHERS:
        yield node.lineno, f"{qual} is case-insensitive on Windows only; use fnmatch.fnmatchcase"
    first = node.args[0] if node.args else None
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "match"
        and not qual.startswith(("re.", "regex."))
        and isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and _GLOB_CHARS & set(first.value)
    ):
        yield node.lineno, "PurePath.match is case-insensitive on Windows only; use fnmatch.fnmatchcase"
    order_keeping = (isinstance(func, ast.Name) and func.id in ORDER_KEEPING_CALLS) or (
        isinstance(func, ast.Attribute) and func.attr in ORDER_KEEPING_METHODS
    )
    if order_keeping and any(_is_set_expr(a) or _is_iter_of_set(a) for a in node.args):
        yield node.lineno, "keeps a set's hash order; pass sorted(...) instead"
    listing = qual in LISTING_FUNCTIONS or (isinstance(func, ast.Attribute) and func.attr in LISTING_METHODS)
    if listing and not _feeds_order_free_consumer(node, parents):
        label = qual if qual else f".{func.attr}()" if isinstance(func, ast.Attribute) else "listing"
        yield node.lineno, f"{label} in file-system order; wrap it in sorted(...)"


@pytest.mark.parametrize("package", _selected(LINTED))
def test_no_nondeterminism(package: str) -> None:
    """Analysis code reads no clock or entropy and never depends on hash or file-system order."""
    problems = sorted({f"{m.rel}:{line}: {msg}" for m in _modules(package) for line, msg in _violations(m)})
    assert not problems, "\n".join(problems)


# --- self-tests: the lint must catch what it claims to catch ---------------------------------
_BAD = {
    "import random": "imports 'random'",
    "import time\nt = time.time()": "reads the clock (time.time)",
    "from time import perf_counter\nperf_counter()": "reads the clock (time.perf_counter)",
    "import datetime\ndatetime.datetime.now()": "reads the clock (datetime.datetime.now)",
    "from datetime import datetime as dt\ndt.utcnow()": "reads the clock (datetime.datetime.utcnow)",
    "import numpy as np\nnp.random.default_rng(1)": "uses numpy.random.default_rng",
    "import uuid\nuuid.uuid4()": "uses entropy (uuid.uuid4)",
    "x = hash('a')": "builtin hash()",
    "for x in {1, 2}:\n    pass": "iterates a set",
    "y = [p for p in set(z)]": "iterates a set",
    "import os\nos.environ['A']": "reads the process environment (os.environ)",
    "import os\nos.listdir('.')": "os.listdir in file-system order",
    "from pathlib import Path\nfor p in Path('.').iterdir():\n    pass": ".iterdir() in file-system order",
    "import os\nfor a in os.walk('.'):\n    pass": "os.walk lists",
    "import os\nfor r, d, f in os.walk('.'):\n    d.sort()\n    for n in f:\n        pass": "os.walk lists",
    "import fnmatch\nfnmatch.fnmatch(a, b)": "use fnmatch.fnmatchcase",
    "import fnmatch\nfnmatch.filter(xs, p)": "use fnmatch.fnmatchcase",
    "from fnmatch import fnmatch\nfnmatch(a, b)": "use fnmatch.fnmatchcase",
    "from pathlib import Path\nPath(a).match('*.csv')": "PurePath.match is case-insensitive",
    "x = list({'a', 'b'})": "keeps a set's hash order",
    "x = tuple(set(y))": "keeps a set's hash order",
    "x = ','.join({'a', 'b'})": "keeps a set's hash order",
    "x = next(iter({'a', 'b'}))": "keeps a set's hash order",
    "x = dict.fromkeys({'a', 'b'})": "keeps a set's hash order",
    "x = list(enumerate(frozenset(y)))": "keeps a set's hash order",
}
_GOOD = (
    "from pathlib import Path\nfiles = sorted(Path('.').rglob('*.py'))",
    "from pathlib import Path\nnames = sorted(p.name for p in Path('.').iterdir())",
    "from pathlib import Path\nempty = not any(Path('.').iterdir())",
    "import numpy as np\nx = np.zeros(3)",
    "for x in sorted({1, 2}):\n    pass",
    "class K:\n    def __hash__(self):\n        return hash(self.key)",
    "import os\nfor r, d, f in os.walk('.'):\n    d.sort()\n    for n in sorted(f):\n        pass",
    "import fnmatch\nfnmatch.fnmatchcase(a, 'b*')",
    "import re\nre.match('a*', s)",
    "x = list(sorted({'a', 'b'}))",
    "x = ','.join(sorted(y))",
)


def _lint_snippet(
    source: str, module: str = "veyltrace_signalyth.api", package: str = "signalyth"
) -> list[str]:
    mod = SourceModule(package, module, ROOT / "snippet.py", ast.parse(source))
    return [msg for _, msg in _violations(mod)]


@pytest.mark.parametrize(("source", "expected"), sorted(_BAD.items()))
def test_lint_catches(source: str, expected: str) -> None:
    messages = _lint_snippet(source)
    assert any(expected in m for m in messages), messages


@pytest.mark.parametrize("source", _GOOD)
def test_lint_allows(source: str) -> None:
    assert _lint_snippet(source) == []


def test_exemptions_are_module_scoped() -> None:
    assert _lint_snippet("import time\ntime.sleep(0)", "veyltrace_core.textio", "core") == []
    assert _lint_snippet("import time\ntime.sleep(0)") != []
    perf = "import time\ntime.perf_counter()"
    assert _lint_snippet(perf, "veyltrace_core.pipeline", "core") == []
    assert _lint_snippet(perf, "veyltrace_core.io", "core") != []
    rng = "import numpy as np\nnp.random.Generator(np.random.PCG64(1))"
    assert _lint_snippet(rng, "veyltrace_core.rng", "core") == []
    env = "import os\nos.environ.get('VEYLTRACE_DATA')"
    assert _lint_snippet(env, "veyltrace_core.config", "core") == []
    assert _lint_snippet(env, "veyltrace_core.io", "core") != []
    assert _lint_snippet(env, "veyltrace_causivra.sign", "causivra") == []


# --- goldens are compared by content, never by file bytes (D-16; critic gap, accepted) -------
#: Hashers whose use on a fixture path compares bytes (Parquet bytes differ across OSes and
#: library versions). Reading bytes to check a verbatim copy within one machine stays allowed.
_BYTE_HASHERS = frozenset({"sha256_file", "sha256_bytes"})
_FIXTURE_MARKERS = ("golden_path", "golden_file", "fixture_dir", "fixtures")


def _test_files() -> list[Path]:
    roots = [ROOT / "tests", *(p / "tests" for p in sorted(PACKAGES_DIR.iterdir()) if p.is_dir())]
    return sorted(f for root in roots if root.is_dir() for f in root.rglob("*.py"))


def _fixture_byte_hashes(tree: ast.Module) -> Iterator[int]:
    """Lines that hash a fixture path's bytes: sha256_file(golden_path(...)), hashlib on
    fixture bytes, ... (testing.assert_golden / content_sha256 compare canonical content)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name in _BYTE_HASHERS or _dotted(func).startswith("hashlib."):
            text = ast.unparse(node)
            if any(marker in text for marker in _FIXTURE_MARKERS):
                yield node.lineno


def test_goldens_are_compared_by_content() -> None:
    """Tests never hash golden fixture bytes: use testing.assert_golden / content_sha256."""
    problems = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: hashes fixture bytes; use testing.assert_golden"
        for path in _test_files()
        if path.name != Path(__file__).name
        for line in _fixture_byte_hashes(ast.parse(path.read_bytes(), filename=str(path)))
    ]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        ("h = sha256_file(golden_path('slate', 'synth-01'))", True),
        ("h = hashlib.sha256(fixture_dir('x', 'synth-01').joinpath('a').read_bytes())", True),
        ("b = sha256_bytes((ROOT / 'packages' / 'x' / 'fixtures' / 'a.parquet').read_bytes())", True),
        ("b = (ROOT / 'packages' / 'x' / 'fixtures' / 'a.parquet').read_bytes()", False),
        ("h = sha256_file(run_dir / 'slate.json')", False),
        ("assert_golden('slate', golden_path('slate', 'synth-01'), actual)", False),
    ],
)
def test_fixture_byte_hash_rule(source: str, bad: bool) -> None:
    assert bool(list(_fixture_byte_hashes(ast.parse(source)))) is bad
