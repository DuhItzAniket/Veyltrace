"""veyltrace_core.testing: fixture layout, variants, golden comparison by canonical content,
run-dir assembly, upstream locks and make_context (lead decision §2.10; D-16).

The golden fixtures do not exist yet in M0, so these tests build a fake work tree whose
`packages/<producer>/fixtures/synth-01/` is filled from one stub pipeline run.
"""

from __future__ import annotations

import ast
import shutil
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pytest

import veyltrace_core.testing as vt
from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.config import config_sha256, resolve_config
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.ids import run_id as make_run_id
from veyltrace_core.pipeline import run_case
from veyltrace_core.steps import STEPS
from veyltrace_core.testing import fixtures as fixtures_module

CASE = "synth-01"
CASE_ID = make_case_id(CASE)
REAL_ROOT = vt.repo_root()


# --- a fake work tree with producer fixtures -----------------------------------------------------
@pytest.fixture(scope="module")
def stub_run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    summary = run_case(
        "synth", CASE_ID, "off", {}, runs_root=tmp_path_factory.mktemp("runs"), code_commit="fixture"
    )
    assert summary.outcome == "ok", summary.reason
    return summary.run_dir


def _populate(root: Path, run_dir: Path) -> None:
    """Distribute a finished run dir into producer fixture dirs, phase-qualifying evidence."""
    for step in STEPS:
        for contract in step.outputs:
            src = run_dir / CONTRACTS[contract].path
            if not src.is_file():
                continue  # relentra with AI off
            phase = vt.TWO_PHASE[contract][step.name] if contract in vt.TWO_PHASE else None
            dst = (
                root
                / "packages"
                / vt.PRODUCER[contract]
                / "fixtures"
                / CASE
                / vt.fixture_relpath(contract, phase)
            )
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    card_md = root / "packages" / "causivra" / "fixtures" / CASE / "card.md"
    shutil.copyfile(run_dir / "card.md", card_md)


@pytest.fixture
def tree(tmp_path: Path, stub_run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "tree"
    (root / "contracts" / "schemas").mkdir(parents=True)
    _populate(root, stub_run_dir)
    monkeypatch.setattr(fixtures_module, "repo_root", lambda: root)
    yield root


# --- layout and variants ----------------------------------------------------------------------------
def test_repo_root_is_the_work_tree() -> None:
    assert (REAL_ROOT / "packages" / "core" / "pyproject.toml").is_file()


def test_producer_covers_every_run_dir_contract_written_by_a_step() -> None:
    written = {name for step in STEPS for name in step.outputs}
    assert written == set(vt.PRODUCER)
    assert {"answer_key", "bench_result", "calibration", "predicates"}.isdisjoint(vt.PRODUCER)


def test_split_and_fixture_case() -> None:
    assert vt.split_case("synth-01@fake") == ("synth-01", "fake")
    assert vt.split_case("synth-02") == ("synth-02", None)
    assert vt.fixture_case("synth-01", "fake") == "synth-01@fake"
    assert vt.fixture_case("synth-05@silent") == "synth-05@silent"
    with pytest.raises(KeyError, match="unknown fixture case"):
        vt.fixture_case("synth-09")
    with pytest.raises(KeyError, match="unknown fixture variant"):
        vt.fixture_case("synth-02", "fake")
    with pytest.raises(ValueError, match="variant given twice"):
        vt.fixture_case("synth-01@fake", "fake")


def test_variants_table_matches_the_lead_decision() -> None:
    assert set(vt.VARIANTS) == {
        "synth-01@fake",
        "synth-01@detected",
        "synth-01@metrics",
        "synth-01@logs",
        "synth-01@traces",
        "synth-01@events",
        "synth-01@noevents",
        "synth-05@silent",
    }
    for name, variant in vt.VARIANTS.items():
        assert name.split("@")[0] == variant.base_case and variant.base_case in vt.SYNTH_CASES
    assert vt.VARIANTS["synth-01@fake"].ai_mode == "record"
    assert vt.VARIANTS["synth-05@silent"].generator == "silent"
    assert vt.VARIANTS["synth-01@noevents"].overrides == {"infralume.sources.drop": ["events"]}


@pytest.mark.parametrize("name", sorted(vt.VARIANTS))
def test_every_variant_override_resolves_against_the_real_config(name: str) -> None:
    variant = vt.VARIANTS[name]
    resolve_config(
        variant.overrides, config_dir=REAL_ROOT / "config", dataset="synth", ai_mode=variant.ai_mode
    )


def test_fixture_relpath_phase_qualifies_two_phase_contracts() -> None:
    assert vt.fixture_relpath("evidence", "main") == "evidence.main.parquet"
    assert vt.fixture_relpath("evidence", "final") == "evidence.final.parquet"
    assert vt.fixture_relpath("graph.edges") == "graph/edges.parquet"
    with pytest.raises(ValueError, match="two versions"):
        vt.fixture_relpath("evidence")
    with pytest.raises(ValueError, match="one version"):
        vt.fixture_relpath("slate", "main")
    with pytest.raises(KeyError, match="no golden fixture"):
        vt.fixture_relpath("answer_key")


def test_golden_paths_mirror_the_run_dir() -> None:
    assert vt.golden_path("slate", CASE) == REAL_ROOT / "packages/causatrix/fixtures/synth-01/slate.json"
    assert vt.golden_path("alert", CASE, variant="detected") == (
        REAL_ROOT / "packages/core/fixtures/synth-01@detected/alert.json"
    )
    assert (
        vt.golden_file("causivra", CASE, "card.md")
        == REAL_ROOT / "packages/causivra/fixtures/synth-01/card.md"
    )
    with pytest.raises(ValueError):
        vt.golden_file("causivra", CASE, "../escape.md")


def test_missing_golden_names_the_update_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fixtures_module, "repo_root", lambda: tmp_path)
    with pytest.raises(ArtifactMissing) as info:
        vt.golden("slate", CASE)
    assert any("--package causatrix --update-golden" in note for note in info.value.__notes__)


# --- golden and assert_golden ---------------------------------------------------------------------------
def test_golden_returns_io_read_types(tree: Path) -> None:
    assert isinstance(vt.golden("slate", CASE), models.Slate)
    assert isinstance(vt.golden("evidence", CASE, phase="main"), pa.Table)


def test_assert_golden_accepts_models_mappings_tables_and_paths(tree: Path, stub_run_dir: Path) -> None:
    slate = io.read_model("slate", stub_run_dir, models.Slate)
    vt.assert_golden(slate, "slate", CASE)
    vt.assert_golden(slate.model_dump(mode="json", by_alias=True), "slate", CASE)
    vt.assert_golden(stub_run_dir / "verdict.json", "verdict", CASE)
    vt.assert_golden(io.read("evidence", stub_run_dir), "evidence", CASE, phase="final")
    bare = io.read_table("evidence", stub_run_dir).replace_schema_metadata(None)  # AI off: main = final
    vt.assert_golden(bare, "evidence", CASE, phase="main")  # no metadata: skipped


def test_assert_golden_reports_a_diff(tree: Path, stub_run_dir: Path) -> None:
    slate = io.read_model("slate", stub_run_dir, models.Slate)
    changed = slate.model_dump(mode="json", by_alias=True)
    changed["k"] = slate.k + 1
    with pytest.raises(AssertionError, match=r'(?s)slate differs.*-.*"k": 5.*\+.*"k": 6'):
        vt.assert_golden(changed, "slate", CASE)


def _row(schema: pa.Schema, i: int, x: float) -> dict[str, object]:
    row: dict[str, object] = {}
    for field in schema:
        if pa.types.is_string(field.type):
            row[field.name] = f"s{i}"
        elif pa.types.is_integer(field.type):
            row[field.name] = i
        elif pa.types.is_floating(field.type):
            row[field.name] = x
        elif pa.types.is_boolean(field.type):
            row[field.name] = i % 2 == 0
        else:
            row[field.name] = [f"v{i}"]
    return row


def test_table_content_ignores_row_order_and_float_noise() -> None:
    schema = io.arrow_schema("graph.edges")
    a = pa.Table.from_pylist([_row(schema, 1, 0.1 + 0.2), _row(schema, 2, 1.0)], schema=schema)
    b = pa.Table.from_pylist([_row(schema, 2, 1.0), _row(schema, 1, 0.3)], schema=schema)
    c = pa.Table.from_pylist([_row(schema, 2, 1.0), _row(schema, 1, 0.31)], schema=schema)
    assert vt.content_lines("graph.edges", a) == vt.content_lines("graph.edges", b)
    assert vt.content_sha256("graph.edges", a) == vt.content_sha256("graph.edges", b)
    assert vt.content_lines("graph.edges", a) != vt.content_lines("graph.edges", c)


def test_jsonl_content_is_one_canonical_line_per_record() -> None:
    assert vt.content_lines("agent_trace", []) == []


# --- fixture_run_dir ---------------------------------------------------------------------------------
def test_fixture_run_dir_through_alert(tree: Path, tmp_path: Path) -> None:
    run_dir = vt.synth_run_dir(CASE, tmp_path)
    names = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file())
    assert names == sorted(
        [
            "alert.json",
            "case_manifest.json",
            *(CONTRACTS[n].path for n in vt.PRODUCER if n.startswith("telemetry.")),
        ]
    )


def test_fixture_run_dir_switches_evidence_phase(tree: Path, tmp_path: Path) -> None:
    final = tree / "packages/faultloom/fixtures/synth-01/evidence.final.parquet"
    final.write_bytes(b"final-sentinel")  # copied verbatim; never parsed by fixture_run_dir
    main = (tree / "packages/faultloom/fixtures/synth-01/evidence.main.parquet").read_bytes()
    before = vt.fixture_run_dir(CASE, tmp_path / "a", through="causatrix")
    after = vt.fixture_run_dir(CASE, tmp_path / "b", through="causentra")
    assert (before / "evidence.parquet").read_bytes() == main
    assert (after / "evidence.parquet").read_bytes() == b"final-sentinel"
    assert not (after / "proposals.json").exists()  # AI off: Relentra is skipped
    default = vt.fixture_run_dir(CASE, tmp_path / "c")
    assert (default / "card.json").is_file() and (default / "card.md").is_file()
    assert not (default / "run_manifest.json").exists()


def test_fixture_run_dir_include_and_missing(tree: Path, tmp_path: Path) -> None:
    run_dir = vt.fixture_run_dir(CASE, tmp_path / "a", through="alert", include=["verdict"])
    assert (run_dir / "verdict.json").is_file()
    (tree / "packages/core/fixtures/synth-01/alert.json").unlink()
    with pytest.raises(ArtifactMissing):
        vt.fixture_run_dir(CASE, tmp_path / "b", through="alert")


def test_fixture_run_dir_for_an_ai_variant_needs_relentra_fixtures(tree: Path, tmp_path: Path) -> None:
    src = tree / "packages/infralume/fixtures/synth-01"
    shutil.copytree(src, tree / "packages/infralume/fixtures/synth-01@fake")
    for producer in ("core", "signalyth", "anomara", "causync", "causalith", "faultloom", "causatrix"):
        shutil.copytree(
            tree / f"packages/{producer}/fixtures/synth-01",
            tree / f"packages/{producer}/fixtures/synth-01@fake",
        )
    with pytest.raises(ArtifactMissing):
        vt.fixture_run_dir(CASE, tmp_path, through="relentra", variant="fake")


# --- upstream.lock.json ----------------------------------------------------------------------------
def test_upstream_lock_round_trip_and_staleness(tree: Path) -> None:
    assert vt.stale_upstream("causatrix", CASE) == ("causatrix/synth-01: no upstream.lock.json",)
    path = vt.write_upstream_lock("causatrix", CASE)
    assert path.name == vt.UPSTREAM_LOCK and path.read_bytes().endswith(b"\n")
    lock = vt.read_upstream_lock(path)
    assert lock == vt.compute_upstream_lock("causatrix", CASE)
    labels = [name for name, _ in lock.entries]
    assert "faultloom/evidence.main.parquet" in labels and "anomara/onsets.json" in labels
    assert not any(label.startswith("causatrix/") for label in labels)
    assert not any("evidence.final" in label for label in labels)  # claim pass comes after causatrix
    assert vt.stale_upstream("causatrix", CASE) == ()

    onsets_path = tree / "packages/anomara/fixtures/synth-01/onsets.json"
    onsets = io.read_path("onsets", onsets_path)
    assert isinstance(onsets, models.Onsets)
    io.write_path("onsets", onsets.model_copy(update={"t_onset_ns": onsets.t_onset_ns + 1}), onsets_path)
    assert vt.stale_upstream("causatrix", CASE) == ("changed upstream fixture anomara/onsets.json",)


def test_upstream_lock_hashes_content_not_bytes(tree: Path) -> None:
    vt.write_upstream_lock("causentra", CASE)
    slate_path = tree / "packages/causatrix/fixtures/synth-01/slate.json"
    slate_path.write_bytes(slate_path.read_bytes().replace(b"\n", b"\r\n"))  # a CRLF checkout
    manifest = tree / "packages/infralume/fixtures/synth-01/case_manifest.json"
    manifest.write_bytes(b"  " + manifest.read_bytes())  # whitespace only
    assert vt.stale_upstream("causentra", CASE) == ()


def test_upstream_lock_reports_new_and_removed_fixtures(tree: Path) -> None:
    vt.write_upstream_lock("causivra", CASE)
    (tree / "packages/causentra/fixtures/synth-01/verdict.json").unlink()
    cassette = tree / "packages/relentra/fixtures/synth-01/cassette"
    cassette.mkdir(parents=True)
    (cassette / "ab.json").write_text("{}\n", encoding="utf-8")
    assert vt.stale_upstream("causivra", CASE) == (
        "removed upstream fixture causentra/verdict.json",
        "new upstream fixture relentra/cassette/ab.json",
    )


def test_read_upstream_lock_rejects_garbage(tmp_path: Path) -> None:
    path = tmp_path / "upstream.lock.json"
    path.write_text('{"consumer": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        vt.read_upstream_lock(path)


# --- make_context ------------------------------------------------------------------------------------
def test_make_context_matches_what_the_pipeline_would_build(tree: Path, tmp_path: Path) -> None:
    run_dir = vt.synth_run_dir(CASE, tmp_path)
    ctx = vt.make_context("signalyth", run_dir)
    assert ctx.case_id == CASE_ID and ctx.dataset == "synth" and ctx.step == "signalyth"
    resolved = resolve_config({}, config_dir=REAL_ROOT / "config", dataset="synth", ai_mode="off")
    assert ctx.run_id == make_run_id(CASE_ID, config_sha256(resolved), "fixture", "off")
    assert ctx.cassette_dir is None
    manifest = ctx.read("case_manifest")
    assert isinstance(manifest, models.CaseManifest) and manifest.t_alert_hint_ns is None  # D-15
    alert_ctx = vt.make_context("core", run_dir)
    assert alert_ctx.step == "alert"
    seen = alert_ctx.read("case_manifest")
    assert isinstance(seen, models.CaseManifest) and seen.t_alert_hint_ns is not None


def test_make_context_phases_overrides_and_ai(tmp_path: Path) -> None:
    claim = vt.make_context("faultloom", tmp_path, phase="claim_pass", case_id=CASE_ID)
    assert claim.step == "faultloom.claim_pass" and claim.phase == "claim_pass"
    shifted = vt.make_context("core", tmp_path, case_id=CASE_ID, overrides={"core.alert.shift_s": 60})
    assert shifted.config.core["alert"]["shift_s"] == 60
    assert shifted.run_id != vt.make_context("core", tmp_path, case_id=CASE_ID).run_id
    rec = vt.make_context("relentra", tmp_path, case_id=CASE_ID, ai_mode="record")
    assert rec.cassette_dir == tmp_path / "cassette" and rec.ai_mode == "record"


def test_make_context_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="case_manifest"):
        vt.make_context("signalyth", tmp_path)
    with pytest.raises(ValueError, match="no pipeline step"):
        vt.make_context("signalyth", tmp_path, phase="card", case_id=CASE_ID)


def test_testing_package_never_imports_synth() -> None:
    package = Path(vt.__file__).parent
    for source in sorted(package.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith("veyltrace_core.synth"), source.name
