"""T1 -- build the controlled XLSX fixture and its truth manifest.

Run directly to (re)generate the fixture::

    python fixtures/build_fixture.py

The output is byte-deterministic: the ZIP entry timestamps are pinned and the
part order and shared-string order are fixed, so rebuilding on any machine
yields the same SHA-256. ``fixtures/rebuild_and_diff.py`` proves that, and
``tests/test_fixture_harness.py`` asserts it.

The fixture is *written by hand* rather than by a workbook library. That is
deliberate: the point of the fixture is to contain the exact constructs under
test (an error cell, a formula with no cached value, a present-but-blank cell,
a coordinate with no cell element, ragged rows) and to be readable by both an
independent stdlib reader and the C06/C07 binding.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# Works both as ``python fixtures/build_fixture.py`` and as
# ``from fixtures import build_fixture``.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fixtures import xlsx_writer  # type: ignore[no-redef]
else:
    from . import xlsx_writer

FIXTURE_NAME = "luohai_tabular_controlled.xlsx"
TRUTH_NAME = "citation_truth.json"
MANIFEST_NAME = "fixture_manifest.json"

_SCHEMA = "seaflow-v2.1-fixture-manifest/v1"

ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
TRUTH_DIR = ROOT / "truth"


# --------------------------------------------------------------------------
# fixture content specification
# --------------------------------------------------------------------------

#: Cell specification: ``int|float`` -> number, ``str`` -> shared string,
#: ``("inline", text)`` -> inline string, ``("error", code)`` -> error value,
#: ``("formula", text, cached)`` -> formula with cached value,
#: ``("formula", text, None)`` -> formula with no cached value,
#: ``("empty",)`` -> present ``<c/>`` element with no value,
#: ``None`` -> no cell element at all (absent).
SheetSpec = Sequence[Sequence[Any]]

SHEETS: tuple[tuple[str, SheetSpec], ...] = (
    (
        "CitationTable",
        (
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 42],
            [None, None, None],
            [None, None, None],
            ["Ningbo", 11, None],
        ),
    ),
    (
        "LossTable",
        (
            ["Sample", "Detail", "Unresolved"],
            [("error", "#DIV/0!"), ("formula", "1+2", 3), ("formula", "1+2", None)],
        ),
    ),
    (
        "CnTable",
        (
            ["港口", "2023", "2024"],
            ["上海", 223, 270],
            ["宁波", 165, 194],
        ),
    ),
    (
        "RaggedTable",
        (
            ["Port", "2023", "2024"],
            ["Shanghai", ("empty",), None],
            ["Ningbo", 11, 42],
            ["Shanghai", "42", 7],
        ),
    ),
    ("EmptyCase", ()),
)

SHARED_STRINGS: tuple[str, ...] = (
    "",
    "Port",
    "Shanghai",
    "Ningbo",
    "港口",
    "上海",
    "宁波",
    "2023",
    "2024",
    "Sample",
    "Detail",
    "Unresolved",
    "42",
)

#: Coordinates with no ``<c>`` element at all -- the "absent" cases.
ABSENT_COORDINATES: tuple[tuple[str, str], ...] = (
    ("CitationTable", "A4"),
    ("CitationTable", "B4"),
    ("CitationTable", "C4"),
    ("CitationTable", "A5"),
    ("CitationTable", "B5"),
    ("CitationTable", "C5"),
    ("CitationTable", "C6"),
    ("RaggedTable", "C2"),
)

#: The known silent-loss statement for this fixture. The extraction path must
#: report these, or report a broader loss -- never a clean success.
KNOWN_SILENT_LOSS: tuple[Mapping[str, str], ...] = (
    {
        "id": "error_value",
        "coordinate": "LossTable!A2",
        "construct": "t=\"e\" error value #DIV/0!",
        "expected_signal": "loss:absent|empty|unsupported|error-kind cell",
        "why": "the V2.0C AU-03 record shows this arriving as \"\" through the "
               "calamine binding, indistinguishable from an empty cell",
    },
    {
        "id": "unresolved_formula",
        "coordinate": "LossTable!C2",
        "construct": "<f>1+2</f> with no <v>",
        "expected_signal": "loss:unsupported plus formula text retained",
        "why": "a formula with no cached value must not be reported as blank",
    },
    {
        "id": "present_but_blank",
        "coordinate": "RaggedTable!B2",
        "construct": "<c r=\"B2\" t=\"s\"><v>0</v></c> pointing at an empty "
                     "shared string",
        "expected_signal": "loss:empty",
        "why": "empty must stay distinct from absent",
    },
    {
        "id": "coordinate_absent",
        "coordinate": "RaggedTable!C2",
        "construct": "no cell element inside the declared region bounds",
        "expected_signal": "loss:absent",
        "why": "a missing coordinate is not an empty value",
    },
)

CITATION_TRUTH: Mapping[str, Any] = {
    "schema_version": "seaflow-v2.1-citation-truth/v1",
    "fixture": FIXTURE_NAME,
    "query": "the 2024 throughput of the Shanghai row in the first table",
    "expected_answer": 42,
    "tables": {
        "CitationTable": {
            "sheet_name": "CitationTable",
            "bounds": "A1:C3",
            "label_cell": None,
            "header_row": 1,
            "column_headers": {"2023": "B", "2024": "C"},
            "row_label_column": "A",
            "detected_as": "two blocks at the default gap tolerance: A1:C3 and "
                           "A6:B6; one region A1:C6 at gap_tolerance >= 3",
            "trailing_block": {
                "bounds": "A6:B6",
                "note": "row 6 holds a label and one value but no third cell, so "
                        "the detector emits it as its own one-row block rather "
                        "than silently extending the table above it",
            },
        },
        "LossTable": {
            "sheet_name": "LossTable",
            "bounds": "A1:C2",
            "header_row": 1,
            "column_headers": {"Detail": "B", "Unresolved": "C"},
            "row_label_column": "A",
        },
        "CnTable": {
            "sheet_name": "CnTable",
            "bounds": "A1:C3",
            "header_row": 1,
            "column_headers": {"2023": "B", "2024": "C"},
            "row_label_column": "A",
        },
        "RaggedTable": {
            "sheet_name": "RaggedTable",
            "bounds": "A1:C4",
            "header_row": 1,
            "column_headers": {"2023": "B", "2024": "C"},
            "row_label_column": "A",
            "ragged_row": 2,
            "note": "row 2 is short of the region width (B2 is present but "
                    "blank, C2 has no cell element); row 4 also demonstrates "
                    "that the text '42' is not the number 42",
        },
    },
    "recurrence_facts": {
        "value_42_occurrences": [
            "CitationTable!C2",
            "CitationTable!C3",
            "RaggedTable!C3",
        ],
        "row_header_shanghai_occurrences": [
            "CitationTable!A2",
            "CnTable!A2",
        ],
        "row_header_ningbo_occurrences": [
            "CitationTable!A3",
            "CitationTable!A6",
            "RaggedTable!A3",
        ],        "column_header_2024_occurrences": [
            "CitationTable!C1",
            "CnTable!C1",
            "RaggedTable!C1",
        ],
        "note": "The row label and the column header are each non-unique. A row "
                "label alone matches every cell in that row (three cells), and "
                "the pair (Shanghai, 2024) matches two different tables "
                "(CitationTable!C2 and RaggedTable!C2). Worksheet/bounds "
                "identity is therefore required, not merely convenient. An "
                "earlier plan note claimed the intersection alone was "
                "sufficient; that claim was wrong, and the fixture keeps the "
                "counter-example rather than hiding it.",
    },
    "canonical_citation": {
        "unit": "CitationTable A1:C3",
        "region_id": "table:CitationTable:A1:C3",
        "sheet_name": "CitationTable",
        "row_header": "Shanghai",
        "row_index": 2,
        "column_header": "2024",
        "column_index": 3,
        "ref": "C2",
        "value": 42,
        "table_context_required": True,
        "reason": "three cells hold the number 42, a row label alone matches "
                  "three cells, and the pair (Shanghai, 2024) matches two "
                  "different tables; only worksheet + bounds + row header + "
                  "column header isolates exactly one cell",
    },
    "interpretations": [
        {
            "id": "cell_only_42",
            "selector": {"value": 42},
            "resolves_query": False,
            "reason": "42 occurs at CitationTable!C2, CitationTable!C3 and "
                      "RaggedTable!C3; a bare value does not locate anything",
        },
        {
            "id": "bare_row_label_shanghai",
            "selector": {"row_header": "Shanghai"},
            "resolves_query": False,
            "reason": "a row label matches every cell of that row, so it can "
                      "never identify a single cell",
        },
        {
            "id": "row_label_plus_column_without_table_context",
            "selector": {"row_header": "Shanghai", "column_header": "2024"},
            "resolves_query": False,
            "reason": "the same intersection matches CitationTable!C2 and "
                      "RaggedTable!C2, so header-only selection is not unique",
        },
        {
            "id": "row_label_plus_column_inside_table",
            "selector": {
                "sheet_name": "CitationTable",
                "region_id": "table:CitationTable:A1:C3",
                "row_header": "Shanghai",
                "column_header": "2024",
            },
            "resolves_query": True,
            "expected_ref": "C2",
        },
        {
            "id": "cjk_row_label_plus_column_inside_table",
            "selector": {
                "sheet_name": "CnTable",
                "region_id": "table:CnTable:A1:C3",
                "row_header": "上海",
                "column_header": "2024",
            },
            "resolves_query": True,
            "expected_ref": "C3",
            "note": "the CJK twin of the canonical query; without table "
                    "identity the two are indistinguishable",
        },
        {
            "id": "empty_cell_inside_region",
            "selector": {"sheet_name": "RaggedTable", "ref": "B2"},
            "resolves_query": True,
            "expected_ref": "B2",
            "expected_value_kind": "empty",
        },
        {
            "id": "absent_coordinate_inside_region",
            "selector": {"sheet_name": "RaggedTable", "ref": "C2"},
            "resolves_query": True,
            "expected_ref": "C2",
            "expected_value_kind": "absent",
        },
        {
            "id": "coordinate_outside_region",
            "selector": {"sheet_name": "CitationTable", "ref": "C7"},
            "resolves_query": False,
            "reason": "C7 is outside the region bounds",
        },
    ],
}


# --------------------------------------------------------------------------
# package assembly (shared writer -- see fixtures/xlsx_writer.py)
# --------------------------------------------------------------------------


def build_spec() -> xlsx_writer.XlsxSpec:
    """Translate the fixture specification into a writer specification."""
    return xlsx_writer.XlsxSpec(
        sheets=tuple(
            xlsx_writer.SheetDef(name=name, rows=rows) for name, rows in SHEETS
        ),
        shared_strings=SHARED_STRINGS,
    )


def build_parts() -> dict[str, bytes]:
    """Return every package part as ``{name: bytes}`` in a fixed order."""
    return xlsx_writer.build_parts(build_spec())


def build_workbook_bytes() -> bytes:
    """Serialise the package deterministically."""
    return xlsx_writer.build_workbook_bytes(build_spec())


# --------------------------------------------------------------------------
# truth manifest
# --------------------------------------------------------------------------


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_truth(workbook_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "seaflow-v2.1-fixture-truth/v1",
        "fixture": FIXTURE_NAME,
        "fixture_sha256": workbook_sha256,
        "provisional": True,
        "workbook_date_system": "1900",
        "sheets": [name for name, _ in SHEETS],
        "shared_strings": list(SHARED_STRINGS),
        "absent_coordinates": [
            {"sheet": sheet, "ref": ref} for sheet, ref in ABSENT_COORDINATES
        ],
        "known_silent_loss": [dict(item) for item in KNOWN_SILENT_LOSS],
        "citation_truth": CITATION_TRUTH,
    }


def build_manifest(workbook_sha256: str, workbook_bytes: int) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA,
        "phase": "V2.1-T1",
        "fixture": FIXTURE_NAME,
        "sha256": workbook_sha256,
        "bytes": workbook_bytes,
        "determinism": {
            "zip_member_timestamps": "pinned to 1980-01-01T00:00:00",
            "part_order": "fixed by build_parts()",
            "shared_string_order": "fixed by SHARED_STRINGS",
            "expected_byte_identical_rebuild": True,
        },
        "sheets": [
            {
                "name": name,
                "index": index,
                "declared_rows": len(spec),
                "spec": "hand-written OOXML; see fixtures/build_fixture.py",
            }
            for index, (name, spec) in enumerate(SHEETS, start=1)
        ],
        "truth": TRUTH_NAME,
        "generated_by": "fixtures/build_fixture.py",
        "purpose": (
            "controlled XLSX covering repeated labels, two tables in one sheet, "
            "an error value, an unresolved formula, a present-but-blank cell, an "
            "absent coordinate and a ragged row"
        ),
    }


def write_fixture(out_dir: Path | None = None, truth_dir: Path | None = None) -> dict[str, Any]:
    """Write the workbook, truth manifest and fixture manifest. Returns the manifest."""
    out_dir = Path(out_dir or GENERATED_DIR)
    truth_dir = Path(truth_dir or TRUTH_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    payload = build_workbook_bytes()
    digest = _sha256(payload)

    workbook_path = out_dir / FIXTURE_NAME
    workbook_path.write_bytes(payload)

    truth = build_truth(digest)
    (truth_dir / TRUTH_NAME).write_text(
        json.dumps(truth, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
)

    manifest = build_manifest(digest, len(payload))
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
)
    return manifest


def main() -> int:
    manifest = write_fixture()
    print(f"{FIXTURE_NAME} sha256={manifest['sha256']} bytes={manifest['bytes']}")
    print(f"written to {GENERATED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
