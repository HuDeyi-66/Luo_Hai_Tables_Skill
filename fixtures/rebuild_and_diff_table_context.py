"""V2.1.1 -- repeat-and-diff harness for the table-context fixture.

Usage::

    python fixtures/rebuild_and_diff_table_context.py --runs 3

Proves three things the context experiment depends on:

1. the context fixture rebuilds byte-identically;
2. the candidate contexts are computed deterministically, not merely
   "usually the same" -- a fingerprint that drifted between runs would make the
   whole collision matrix meaningless;
3. the measured ambiguity matrix is stable across runs.

Exit code 0 when every run agrees, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.artifact import Artifact  # noqa: E402
from skills.luohai import ooxml, table_context, table_observe  # noqa: E402
from skills.luohai.backends import FixtureXlsxBackend  # noqa: E402
from skills.luohai import TabularEvidenceSkill  # noqa: E402
from fixtures import build_table_context_fixture as builder  # noqa: E402

FIXTURE_PATH = builder.GENERATED_DIR / builder.FIXTURE_NAME
MANIFEST_PATH = builder.GENERATED_DIR / builder.MANIFEST_NAME


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def contexts_for(gap_tolerance: int = 0):
    artifact = Artifact.from_file(FIXTURE_PATH, "art-context")
    result = TabularEvidenceSkill(FixtureXlsxBackend()).run(
        artifact, source_id="src-context", options={"gap_tolerance": gap_tolerance}
    )
    contexts: dict[str, table_context.TableContext] = {}
    counters: dict[str, int] = {}
    for unit in result.units:
        block = (unit.payload or {}).get("tabular")
        if not isinstance(block, dict):
            continue
        sheet = str(block.get("sheet_name"))
        counters[sheet] = counters.get(sheet, 0) + 1
        contexts[f"{sheet}#{counters[sheet]}"] = (
            table_context.build_table_context(
                block,
                hidden_rows=block.get("hidden_rows") or (),
                hidden_columns=block.get("hidden_columns") or (),
                merged_ranges=block.get("merged_ranges") or (),
            )
        )
    return artifact, result, contexts


def check_fixture(runs: int) -> list[str]:
    problems: list[str] = []
    digests = [_sha256(builder.build_workbook_bytes()) for _ in range(runs)]
    if len(set(digests)) != 1:
        problems.append(f"identity fixture rebuild is not deterministic: {set(digests)}")

    committed = FIXTURE_PATH.read_bytes() if FIXTURE_PATH.is_file() else b""
    if not committed:
        problems.append(f"committed identity fixture is missing: {FIXTURE_PATH}")
    elif _sha256(committed) != digests[0]:
        problems.append(
            "rebuild does not match the committed context fixture; regenerate "
            "the fixture and truth manifest together"
        )
    if MANIFEST_PATH.is_file():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if manifest["sha256"] != digests[0]:
            problems.append(
                f"manifest pins {manifest['sha256']} but rebuild produced {digests[0]}"
            )
    else:
        problems.append(f"identity fixture manifest is missing: {MANIFEST_PATH}")

    print(f"[fixture] {runs} rebuild(s) -> sha256={digests[0]}")
    return problems


def check_identity_determinism(runs: int) -> list[str]:
    problems: list[str] = []
    baseline: dict[str, Any] | None = None
    baseline_json = ""
    for index in range(1, runs + 1):
        _, _, contexts = contexts_for()
        payload = {name: ctx.as_dict() for name, ctx in sorted(contexts.items())}
        rendered = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if baseline is None:
            baseline, baseline_json = payload, rendered
            print(f"[context] baseline: {len(payload)} regions")
            fingerprints = {
                name: ctx.values["content_fingerprint"][:12]
                for name, ctx in sorted(contexts.items())
            }
            print(f"[context] fingerprints: {fingerprints}")
        elif rendered != baseline_json:
            problems.append(f"table context run {index} differs from run 1")
            for name in sorted(set(payload) | set(baseline or {})):
                if payload.get(name) != (baseline or {}).get(name):
                    problems.append(f"  differing region: {name}")
    return problems


def check_matrix_stability(runs: int) -> list[str]:
    problems: list[str] = []
    baseline_json = ""
    for index in range(1, runs + 1):
        _, _, contexts = contexts_for()
        matrix = table_context.build_ambiguity_matrix(contexts)
        rendered = json.dumps(matrix, sort_keys=True, ensure_ascii=False)
        if not baseline_json:
            baseline_json = rendered
            summary = {
                candidate: {
                    scope: data["unique_count"]
                    for scope, data in measurement["by_scope"].items()
                }
                for candidate, measurement in matrix["by_candidate"].items()
            }
            print(f"[matrix ] unique counts per candidate/scope: {summary}")
        elif rendered != baseline_json:
            problems.append(f"ambiguity matrix run {index} differs from run 1")
    return problems


def check_declared_observation_stability(runs: int) -> list[str]:
    """The declared-vs-inferred comparison must be stable too."""
    problems: list[str] = []
    baseline = ""
    for index in range(1, runs + 1):
        _, result, _ = contexts_for()
        package = ooxml.read_package(str(FIXTURE_PATH))
        observation = table_observe.compare_declared_and_inferred(
            declared_tables_by_sheet={
                sheet.name: sheet.declared_tables for sheet in package.sheets
            },
            regions_by_sheet=table_observe.regions_from_result(result),
        )
        rendered = json.dumps(observation.as_dict(), sort_keys=True, ensure_ascii=False)
        if not baseline:
            baseline = rendered
            print(
                f"[observe] declared tables={observation.declared_table_count} "
                f"outcomes={observation.by_status}"
            )
        elif rendered != baseline:
            problems.append(
                f"declared-table observation run {index} differs from run 1"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SeaFlow V2.1.1 table-context repeat-and-diff harness"
    )
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)

    problems: list[str] = []
    problems += check_fixture(args.runs)
    problems += check_identity_determinism(args.runs)
    problems += check_matrix_stability(args.runs)
    problems += check_declared_observation_stability(args.runs)

    print()
    if problems:
        print("CONTEXT DIFF HARNESS: FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"CONTEXT DIFF HARNESS: OK ({args.runs} runs, fixture, contexts, matrix "
        f"and declared observation identical)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
