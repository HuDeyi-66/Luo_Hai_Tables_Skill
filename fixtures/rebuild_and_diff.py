"""T1 -- repeat-and-diff harness for the controlled fixture and the extractor.

Usage::

    python fixtures/rebuild_and_diff.py            # fixture + extraction diff
    python fixtures/rebuild_and_diff.py --runs 3

What it proves
--------------
1. **Fixture determinism.** Rebuilding the workbook several times yields
   byte-identical output, and it matches the committed fixture and the SHA-256
   pinned in ``fixture_manifest.json``.
2. **Extraction determinism.** Running the Skill repeatedly over the fixture
   yields structurally identical ``TableRunResult`` payloads once run identity and
   timestamps are removed. A non-deterministic extractor cannot support a
   citation-oriented workflow, so this is checked rather than assumed.

Exit code is 0 when every run agrees, 1 otherwise.
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

from skills.luohai.contracts import TableArtifact  # noqa: E402
from skills.luohai.backends import FixtureXlsxBackend  # noqa: E402
from skills.luohai import TabularEvidenceSkill  # noqa: E402
from fixtures import build_fixture  # noqa: E402

FIXTURE_PATH = build_fixture.GENERATED_DIR / build_fixture.FIXTURE_NAME
MANIFEST_PATH = build_fixture.GENERATED_DIR / build_fixture.MANIFEST_NAME


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_projection(result: Any) -> dict[str, Any]:
    """The part of a TableRunResult that must not vary between runs."""
    payload = result.as_dict()
    payload.pop("invocation_id", None)
    payload.pop("started_at", None)
    payload.pop("finished_at", None)
    payload.get("producer", {}).pop("run_id", None)
    for unit in payload.get("units", []):
        unit.get("producer", {}).pop("run_id", None)
    return payload


def check_fixture(runs: int) -> list[str]:
    problems: list[str] = []
    digests = [_sha256(build_fixture.build_workbook_bytes()) for _ in range(runs)]
    if len(set(digests)) != 1:
        problems.append(f"fixture rebuild is not deterministic: {sorted(set(digests))}")

    committed = FIXTURE_PATH.read_bytes() if FIXTURE_PATH.is_file() else b""
    if not committed:
        problems.append(f"committed fixture is missing: {FIXTURE_PATH}")
    elif _sha256(committed) != digests[0]:
        problems.append(
            "rebuild does not match the committed fixture; regenerate the "
            "fixture and truth manifest together"
        )

    if MANIFEST_PATH.is_file():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if manifest["sha256"] != digests[0]:
            problems.append(
                f"manifest pins {manifest['sha256']} but rebuild produced {digests[0]}"
            )
        if manifest["bytes"] != len(committed):
            problems.append(
                f"manifest pins {manifest['bytes']} bytes, file has {len(committed)}"
            )
    else:
        problems.append(f"fixture manifest is missing: {MANIFEST_PATH}")

    print(f"[fixture] {runs} rebuild(s) -> sha256={digests[0]}")
    return problems


def check_extraction(runs: int) -> list[str]:
    problems: list[str] = []
    artifact = TableArtifact.from_file(FIXTURE_PATH, "art-fixture")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())

    baseline: dict[str, Any] | None = None
    baseline_json = ""
    for index in range(1, runs + 1):
        result = skill.run(artifact, source_id="src-1")
        projection = stable_projection(result)
        rendered = json.dumps(projection, sort_keys=True, ensure_ascii=False)
        if baseline is None:
            baseline, baseline_json = projection, rendered
            presence = sorted(
                loss for loss in result.diagnostics.observed_loss_kinds
            )
            print(
                f"[extract] baseline: {len(result.units)} units, "
                f"observed loss kinds {presence}, "
                f"complete_success={result.is_complete_success}"
            )
            # A run over this fixture must never look lossless.
            if result.is_complete_success:
                problems.append(
                    "extraction reported a complete success over a fixture that "
                    "is known to contain empty, absent and unsupported values"
                )
            for expected in ("absent", "empty", "unsupported"):
                if expected not in presence:
                    problems.append(
                        f"cell-level loss kind {expected!r} was not surfaced "
                        f"(surfaced: {presence}); the fixture contains it"
                    )
        elif rendered != baseline_json:
            problems.append(f"extraction run {index} differs from run 1")
            for key in sorted(set(projection) | set(baseline)):
                if projection.get(key) != baseline.get(key):
                    problems.append(f"  differing key: {key}")

    return problems


def check_digest_stability(runs: int) -> list[str]:
    """The artifact digest must not change between runs."""
    digests = {
        TableArtifact.from_file(FIXTURE_PATH, f"art-{i}").digest for i in range(runs)
    }
    if len(digests) != 1:
        return [f"artifact digest is unstable: {sorted(digests)}"]
    print(f"[digest ] content digest stable: {sorted(digests)[0][:16]}...")
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SeaFlow V2.1 repeat-and-diff harness")
    parser.add_argument("--runs", type=int, default=3, help="repetitions (default 3)")
    args = parser.parse_args(argv)

    problems: list[str] = []
    problems += check_fixture(args.runs)
    problems += check_digest_stability(args.runs)
    problems += check_extraction(args.runs)

    print()
    if problems:
        print("DIFF HARNESS: FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"DIFF HARNESS: OK ({args.runs} runs, fixture and extraction identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
