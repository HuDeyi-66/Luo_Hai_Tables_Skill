"""V2.1.1 experiment runner: table boundary + context candidate matrix.

Usage::

    python tools/table_context_experiment.py
    python tools/table_context_experiment.py --gap-tolerance 1

Prints, for the controlled context fixture:

1. the detected regions per sheet and what structural facts were observed
   (hidden axes, merges, ragged rows, duplicate headers);
2. the three candidate contexts per region;
3. a pairwise collision matrix saying, per candidate, which table pairs it
   *collapses* -- i.e. which pairs a resolver restricted to that candidate
   could not tell apart;
4. the resolver outcome for a set of probe queries.

Writes ``artifacts/table_context_experiment.json``.

This tool reports. It does not choose a candidate.
"""

from __future__ import annotations

import argparse
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
from skills.luohai.citation import (  # noqa: E402
    Ambiguous,
    Citation,
    CitationSelector,
    TableResolution,
    resolve_citation,
    resolve_table_context,
)
from skills.luohai import TabularEvidenceSkill  # noqa: E402
from fixtures import build_table_context_fixture as builder  # noqa: E402

FIXTURE_PATH = builder.GENERATED_DIR / builder.FIXTURE_NAME

#: Probe queries for the ambiguity experiment. Each is a (name, selector) pair
#: evaluated per unit; the report shows what the resolver did with each.
#: Note there is deliberately no "context hint alone" probe: a context hint
#: names a *table*, and asking for a cell citation from it without saying which
#: cell is a malformed request, not an ambiguity. Table-level context is probed
#: through ``resolve_table_context`` instead.
PROBES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("bare row label within region", {"row_header": "Shanghai"}),
    ("header pair within region", {"row_header": "Shanghai", "column_header": "2024"}),
    ("header pair + value", {"row_header": "Shanghai", "column_header": "2024", "value": 42.0}),
    ("explicit coordinate", {"ref": "C2"}),
)


def load_result(gap_tolerance: int):
    artifact = Artifact.from_file(FIXTURE_PATH, "art-context")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return artifact, skill.run(
        artifact, source_id="src-context", options={"gap_tolerance": gap_tolerance}
    )


def declared_table_report(result) -> dict[str, Any]:
    """Issue 2: compare declared OOXML table metadata with inferred context."""
    package = ooxml.read_package(str(FIXTURE_PATH))
    declared = {sheet.name: sheet.declared_tables for sheet in package.sheets}
    report = table_observe.compare_declared_and_inferred(
        declared_tables_by_sheet=declared,
        regions_by_sheet=table_observe.regions_from_result(result),
    )
    return report.as_dict()


def observed_structural_facts(result) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for unit in result.units:
        block = (unit.payload or {}).get("tabular")
        if not isinstance(block, dict):
            continue
        facts[unit.address.container_id] = {
            "sheet": block.get("sheet_name"),
            "bounds": block.get("bounds"),
            "ragged_rows": list(block.get("ragged_rows") or ()),
            "hidden_rows": list(block.get("hidden_rows") or ()),
            "hidden_columns": list(block.get("hidden_columns") or ()),
            "merged_ranges": list(block.get("merged_ranges") or ()),
            "duplicate_column_headers": list(
                block.get("duplicate_column_headers") or ()
            ),
            "duplicate_row_labels": list(block.get("duplicate_row_labels") or ()),
            "unit_loss": list(unit.loss),
        }
    return facts


def build_contexts(result) -> dict[str, table_context.TableContext]:
    """One table context per region, keyed by a stable experiment name."""
    contexts: dict[str, table_context.TableContext] = {}
    per_sheet_counter: dict[str, int] = {}
    for unit in result.units:
        block = (unit.payload or {}).get("tabular")
        if not isinstance(block, dict):
            continue
        sheet = str(block.get("sheet_name"))
        per_sheet_counter[sheet] = per_sheet_counter.get(sheet, 0) + 1
        name = f"{sheet}#{per_sheet_counter[sheet]}"
        contexts[name] = table_context.build_table_context(
            block,
            hidden_rows=block.get("hidden_rows") or (),
            hidden_columns=block.get("hidden_columns") or (),
            merged_ranges=block.get("merged_ranges") or (),
        )
    return contexts


def run_probes(result) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for name, spec in PROBES:
        matched_tables: list[str] = []
        ambiguous: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for unit in result.units:
            if not unit.address.container_id.startswith("table:"):
                continue
            block = (unit.payload or {}).get("tabular") or {}
            region_handle = block.get("region_id")
            selector_kwargs = {k: v for k, v in spec.items()}
            if "context_hint" in selector_kwargs:
                candidate = selector_kwargs.pop("context_hint")
                hints = (unit.metadata.get("table_context") or {}).get(
                    "context_hints", {}
                )
                selector_kwargs["context_hint"] = hints.get(candidate)
            if selector_kwargs.get("region_id") is None and selector_kwargs.get(
                "context_hint"
            ) is None:
                # Per-unit probing: the unit is the table scope, so no workbook
                # level table context is being claimed.
                selector_kwargs["require_table_context"] = False
            selector = CitationSelector(**selector_kwargs)
            outcome = resolve_citation(unit, selector)
            if isinstance(outcome, Citation):
                matched_tables.append(f"{region_handle}->{outcome.ref}")
            elif isinstance(outcome, Ambiguous):
                ambiguous.append(
                    {"unit": region_handle, "candidates": list(outcome.candidate_refs)}
                )
            else:
                unresolved.append(f"{region_handle}:{outcome.problem}")
        findings.append(
            {
                "probe": name,
                "selector": spec,
                "tables_returning_a_cell": matched_tables,
                "tables_returning_ambiguity": ambiguous,
                "tables_unresolved": unresolved,
            }
        )
    return findings


def run_context_probes(result) -> list[dict[str, Any]]:
    """Ask the table-level question: which table does this hint name?

    Each table's own candidate hint is fed back to ``resolve_table_context``
    across the whole artifact. A candidate that names one table is usable for
    that table; a candidate that matches several is collapsed and the resolver
    must say so. The outcome is table-level: it never reports a cell.
    """
    units = tuple(result.units)
    findings: list[dict[str, Any]] = []
    for unit in units:
        hints = table_context.unit_context_hints(unit)
        if not hints:
            continue
        for candidate in table_context.CANDIDATE_KEYS:
            hint = hints.get(candidate)
            if not hint:
                continue
            outcome = resolve_table_context(units, hint=hint, candidate=candidate)
            if isinstance(outcome, TableResolution) and not outcome.unique:
                findings.append(
                    {
                        "unit": unit.address.container_id,
                        "candidate": candidate,
                        "outcome": "ambiguous",
                        "matching_tables": [
                            f"{c.sheet_name}!{c.bounds}" for c in outcome.candidates
                        ],
                    }
                )
            elif isinstance(outcome, TableResolution):
                findings.append(
                    {
                        "unit": unit.address.container_id,
                        "candidate": candidate,
                        "outcome": "unique",
                        "table_bounds": outcome.table.bounds if outcome.table else None,
                    }
                )
            else:
                findings.append(
                    {
                        "unit": unit.address.container_id,
                        "candidate": candidate,
                        "outcome": "unresolved",
                        "message": outcome.message,
                    }
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2.1.1 table context experiment")
    parser.add_argument("--gap-tolerance", type=int, default=0)
    args = parser.parse_args(argv)

    artifact, result = load_result(args.gap_tolerance)
    contexts = build_contexts(result)
    matrix = table_context.build_collision_matrix(contexts)
    ambiguity = table_context.build_ambiguity_matrix(contexts)
    facts = observed_structural_facts(result)
    probes = run_probes(result)
    context_probes = run_context_probes(result)
    declared = declared_table_report(result)

    report = {
        "schema_version": "seaflow-v2.1.1-table-context-experiment/v1",
        "fixture": builder.FIXTURE_NAME,
        "fixture_sha256": artifact.digest,
        "gap_tolerance": args.gap_tolerance,
        "region_count": len(contexts),
        "regions": {name: ctx.as_dict() for name, ctx in contexts.items()},
        "observed_structural_facts": facts,
        "collision_matrix": matrix,
        "ambiguity_matrix": ambiguity,
        "probes": probes,
        "context_probes": context_probes,
        "declared_table_observation": declared,
        "diagnostics": {
            "warning_codes": sorted(
                {w.code for w in result.diagnostics.warnings}
            ),
            "observed_loss_kinds": list(result.diagnostics.observed_loss_kinds),
            "is_complete_success": result.is_complete_success,
        },
    }

    out_dir = PROJECT_ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "table_context_experiment.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"fixture          : {builder.FIXTURE_NAME} ({artifact.digest[:16]}...)")
    print(f"gap_tolerance    : {args.gap_tolerance}")
    print(f"regions detected : {len(contexts)}")
    print()
    print("regions per sheet:")
    for name in sorted(contexts):
        ctx = contexts[name]
        facts_row = facts.get(ctx.region_id, {})
        extras = []
        if facts_row.get("ragged_rows"):
            extras.append(f"ragged={facts_row['ragged_rows']}")
        if facts_row.get("hidden_columns"):
            extras.append(f"hidden_cols={facts_row['hidden_columns']}")
        if facts_row.get("hidden_rows"):
            extras.append(f"hidden_rows={facts_row['hidden_rows']}")
        if facts_row.get("merged_ranges"):
            extras.append(f"merges={facts_row['merged_ranges']}")
        if facts_row.get("duplicate_column_headers"):
            extras.append(
                f"dup_col_headers={facts_row['duplicate_column_headers']}"
            )
        print(f"  {name:<22} {ctx.bounds:<10} {' '.join(extras)}")

    print()
    print("AMBIGUITY MATRIX -- measured by running each candidate's query.")
    print("A query matching more than one table cannot identify a table.")
    for candidate, measurement in ambiguity["by_candidate"].items():
        for scope, data in measurement["by_scope"].items():
            print(
                f"  candidate {candidate} / {scope:<8} scope: "
                f"{data['unique_count']} uniquely identified, "
                f"{data['ambiguous_count']} ambiguous"
            )
            for entry in data["ambiguous"]:
                print(
                    f"        {entry['table']} -> matches "
                    f"{entry['matching_tables']}"
                )

    print()
    print("PAIRWISE CONTEXT COLLISIONS (expected empty: address is in every candidate)")
    for key in table_context.CANDIDATE_KEYS:
        print(
            f"  candidate {key}: "
            f"{len(matrix['collapsed_context_pairs'][key])} collapsed pair(s)"
        )

    print()
    print("table-level context probes (resolve_table_context):")
    ambiguous_count = sum(1 for f in context_probes if f["outcome"] == "ambiguous")
    for finding in context_probes:
        if finding["outcome"] == "ambiguous":
            print(
                f"  AMBIGUOUS {finding['candidate']}  {finding['unit']}"
                f"  matches {finding['matching_tables']}"
            )
    print(f"  ({ambiguous_count} of {len(context_probes)} context probes ambiguous)")

    print()
    print("DECLARED OOXML TABLE OBSERVATION (Issue 2) -- observation only")
    print(
        f"  declared tables in fixture: {declared['declared_table_count']} "
        f"across {declared['sheets_with_declared_tables']}"
    )
    print(f"  outcomes: {declared['summary']}")
    for comparison in declared["comparisons"]:
        if comparison["declared"] is None:
            continue
        line = (
            f"    {comparison['status']:<13} {comparison['sheet_name']:<18} "
            f"declared {comparison['declared']['ref']:<9} "
            f"inferred {comparison['bounds']}"
        )
        print(line)
        if comparison["disagreements"]:
            print(f"        disagrees on: {comparison['disagreements']}")

    print()
    print("cell-level probes:")
    for finding in probes:
        print(f"  {finding['probe']}")
        print(f"      cell      : {finding['tables_returning_a_cell']}")
        print(f"      ambiguous : {finding['tables_returning_ambiguity']}")
        print(f"      unresolved: {finding['tables_unresolved']}")
    print()
    print(f"report written   : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
