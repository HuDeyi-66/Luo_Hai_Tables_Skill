"""LuoHai example: tabular evidence, cell and range citations.

Run from the repository root::

    python examples/luohai_table_example.py

Reads a committed synthetic workbook fixture, registers it as a source/artifact,
extracts one evidence unit per detected table region, and reconstructs two native
citations:

* a single cell, identified by row and column header inside a named table;
* a rectangular range, which returns every coordinate -- including the empty and
  absent cells -- rather than a tidy grid.

Both are produced by the Skill's own resolver. Ambiguity is reported, not
guessed: a header alone matches a whole row, and the example shows that refusal.
"""

from __future__ import annotations

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills.luohai.contracts import TableArtifact  # noqa: E402
from skills.luohai import (  # noqa: E402
    Ambiguous,
    Citation,
    CitationSelector,
    FixtureXlsxBackend,
    TabularEvidenceSkill,
    resolve_citation,
)
from skills.luohai.citation import RangeCitation  # noqa: E402

FIXTURE = PROJECT_ROOT / "fixtures" / "generated" / "luohai_tabular_controlled.xlsx"


def main() -> int:
    # The Skill takes its input directly: a workbook whose bytes it can
    # re-verify. Source registration is a caller's concern, not the Skill's, so
    # LuoHai needs no registry to be used on its own.
    artifact = TableArtifact.from_file(FIXTURE, "example-port-workbook")

    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    result = skill.run(artifact, source_id="example-port-workbook")

    print(f"artifact      : {artifact.artifact_id} ({artifact.content_digest[:24]}...)")
    print(f"skill         : {result.skill_id}")
    print(f"backend       : {result.diagnostics.backend_id}")
    print(f"units         : {len(result.units)}")
    print(f"complete      : {result.is_complete_success} (loss is reported, not hidden)")
    print()

    print("evidence units")
    for unit in result.units:
        block = (unit.payload or {}).get("tabular")
        if block is None:
            print(f"  {unit.unit_id:<52} container   no table region")
            continue
        print(
            f"  {unit.unit_id:<52} {block['bounds']:<8} "
            f"cells={len(block['cells']):<3} loss={list(unit.loss)}"
        )
    print()

    citation_table = next(
        unit for unit in result.units if unit.unit_id.endswith("CitationTable:A1:C3")
    )

    print("citation: one cell, by row and column header inside a named table")
    outcome = resolve_citation(
        citation_table,
        CitationSelector(
            row_header="Shanghai",
            column_header="2024",
            sheet_name="CitationTable",
            region_id="table:CitationTable:A1:C3",
        ),
    )
    if isinstance(outcome, Citation):
        print(f"  ref         : {outcome.sheet_name}!{outcome.ref}")
        print(f"  value       : {outcome.value!r} ({outcome.value_kind})")
        print(f"  uniqueness  : {outcome.uniqueness}")
        print(f"  context     : {' > '.join(outcome.context_path)}")
    else:
        print(f"  refused     : {type(outcome).__name__}")
    print()

    print("citation: a rectangular range keeps its holes")
    ragged = next(
        unit for unit in result.units if unit.unit_id.endswith("RaggedTable:A1:C4")
    )
    range_outcome = resolve_citation(
        ragged,
        CitationSelector(
            ref_range="A1:C4",
            sheet_name="RaggedTable",
            region_id="table:RaggedTable:A1:C4",
        ),
    )
    if isinstance(range_outcome, RangeCitation):
        print(f"  ref         : {range_outcome.sheet_name}!{range_outcome.ref}")
        print(
            f"  shape       : {range_outcome.row_count} rows x "
            f"{range_outcome.column_count} columns, "
            f"{range_outcome.cell_count} coordinates"
        )
        print(f"  holes       : {[cell.ref for cell in range_outcome.lossy_cells]}")
    else:
        print(f"  refused     : {type(range_outcome).__name__}")
    print()

    print("refusal: a row header alone does not identify a cell")
    ambiguous = resolve_citation(
        citation_table, CitationSelector(row_header="Shanghai", sheet_name="CitationTable")
    )
    if isinstance(ambiguous, Ambiguous):
        print(f"  outcome     : {type(ambiguous).__name__}")
        print(f"  candidates  : {list(ambiguous.candidate_refs)}")
        print(f"  message     : {ambiguous.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
