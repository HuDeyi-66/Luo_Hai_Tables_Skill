"""V2.1.1 -- controlled XLSX fixture for the table-identity spike.

Run directly to (re)generate::

    python fixtures/build_table_context_fixture.py

Separate from the V2.1 fixture on purpose. ``build_fixture.py`` and its output
stay byte-identical so the 147 V2.1 tests keep their pinned hash; this fixture
adds only the boundary shapes the context experiments need.

Coverage (the list is the specification of the spike):

============================  ==================================================
sheet                          what it exercises
============================  ==================================================
``SingleTable``                one unambiguous table
``TwoAdjacentTables``          two tables stacked with *no* blank row, and a
                               changed column structure between them
``BlankSeparated``             two tables separated by exactly one blank row
``MergedCells``                merged header and merged row-label cell
``RaggedRows``                 a row short of the region width
``HiddenAxes``                 hidden column and hidden row
``DuplicateHeaders``           two tables with the same header values
``TwinSameSheet``              two identical tables, same sheet, same values,
                               different addresses
============================  ==================================================
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fixtures import xlsx_writer  # type: ignore[no-redef]
else:
    from . import xlsx_writer

FIXTURE_NAME = "luohai_table_context.xlsx"
TRUTH_NAME = "table_context_truth.json"
MANIFEST_NAME = "table_context_manifest.json"

ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
TRUTH_DIR = ROOT / "truth"

XML_DECL = xlsx_writer.XML_DECL


# --------------------------------------------------------------------------
# fixture content
# --------------------------------------------------------------------------

#: Cell spec is the same mini-language as the V2.1 fixture. ``None`` means the
#: coordinate has no cell element at all.
SHEETS: tuple[xlsx_writer.SheetDef, ...] = (
    xlsx_writer.SheetDef(
        name="SingleTable",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
        ),
    ),
    xlsx_writer.SheetDef(
        name="TwoAdjacentTables",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
            # No blank row: the next block starts immediately.
            ["Metric", "Value"],
            ["Dues", 7],
        ),
    ),
    xlsx_writer.SheetDef(
        name="BlankSeparated",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
            [None, None, None],
            ["Port", "2023", "2024"],
            ["Shanghai", 20, 43],
            ["Ningbo", 21, 98],
        ),
    ),
    xlsx_writer.SheetDef(
        name="MergedCells",
        rows=(
            [("inline", "Annual Throughput"), None, None],
            ["Key", "2023", "2024"],
            [None, 10, 42],
            ["Ningbo", 11, 99],
        ),
        merged_ranges=("A1:C1", "A2:A3"),
    ),
    xlsx_writer.SheetDef(
        name="RaggedRows",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", ("empty",), None],
            ["Ningbo", 11, 99],
        ),
    ),
    xlsx_writer.SheetDef(
        name="HiddenAxes",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            [None, None, None],
            [None, None, None],
            ["Port", "2023", "2024"],
            ["Shanghai", 20, 43],
        ),
        columns=(
            xlsx_writer.ColumnSpec(min_index=3, max_index=3, hidden=True),
            xlsx_writer.ColumnSpec(min_index=4, max_index=4, hidden=True),
        ),
        hidden_rows=(4,),
    ),
    xlsx_writer.SheetDef(
        name="DuplicateHeaders",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
            [None, None, None],
            ["Port", "2024", "2023"],
            ["Shanghai", 270, 223],
        ),
    ),
    xlsx_writer.SheetDef(
        name="TwinSameSheet",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
            [None, None, None],
            [None, None, None],
            [None, None, None],
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
        ),
    ),
    xlsx_writer.SheetDef(
        name="SideBySide",
        rows=(
            ["Port", "2024", None, "Port", "2024"],
            ["Shanghai", 42, None, "Ningbo", 99],
        ),
    ),
    # -- declared OOXML table observation (V2.1 closure patch, Issue 2) -----
    # The declared range and header row match what inference produces.
    xlsx_writer.SheetDef(
        name="DeclaredAgrees",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
        ),
        declared_tables=(
            xlsx_writer.DeclaredTableSpec(
                table_id=1,
                name="DeclaredAgreesTable",
                display_name="DeclaredAgreesTable",
                ref="A1:C3",
                column_names=("Port", "2023", "2024"),
            ),
        ),
    ),
    # Two byte-identical tables that are *individually declared by name*. This
    # is the case inference cannot separate and declared metadata can.
    xlsx_writer.SheetDef(
        name="DeclaredTwins",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
            [None, None, None],
            [None, None, None],
            [None, None, None],
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
        ),
        declared_tables=(
            xlsx_writer.DeclaredTableSpec(
                table_id=2,
                name="DeclaredTwinFirst",
                display_name="DeclaredTwinFirst",
                ref="A1:C3",
                column_names=("Port", "2023", "2024"),
            ),
            xlsx_writer.DeclaredTableSpec(
                table_id=3,
                name="DeclaredTwinSecond",
                display_name="DeclaredTwinSecond",
                ref="A7:C9",
                column_names=("Port", "2023", "2024"),
            ),
        ),
    ),
    # The declared range is wider than the populated block, so the inferred
    # region is narrower than what the author declared. This must surface as a
    # disagreement, not as "no declared table".
    xlsx_writer.SheetDef(
        name="DeclaredMismatch",
        rows=(
            ["Port", "2023", "2024"],
            ["Shanghai", 10, 42],
            ["Ningbo", 11, 99],
        ),
        declared_tables=(
            xlsx_writer.DeclaredTableSpec(
                table_id=4,
                name="DeclaredMismatchTable",
                display_name="DeclaredMismatchTable",
                ref="A1:C5",
                column_names=("Port", "2023", "2024"),
            ),
        ),
    ),
)

SHARED_STRINGS: tuple[str, ...] = (
    "",
    "Port",
    "2023",
    "2024",
    "Shanghai",
    "Ningbo",
    "Metric",
    "Value",
    "Dues",
    "Key",
)

#: Coordinates with no ``<c>`` element: the absent cases.
ABSENT_COORDINATES: tuple[tuple[str, str], ...] = (
    ("TwoAdjacentTables", "C5"),
    ("BlankSeparated", "A4"),
    ("BlankSeparated", "B4"),
    ("BlankSeparated", "C4"),
    ("RaggedRows", "C2"),
    ("HiddenAxes", "A3"),
    ("HiddenAxes", "B3"),
    ("HiddenAxes", "C3"),
    ("HiddenAxes", "A4"),
    ("HiddenAxes", "B4"),
    ("HiddenAxes", "C4"),
    ("DuplicateHeaders", "A4"),
    ("DuplicateHeaders", "B4"),
    ("DuplicateHeaders", "C4"),
    ("TwinSameSheet", "A4"),
    ("TwinSameSheet", "B4"),
    ("TwinSameSheet", "C4"),
    ("TwinSameSheet", "A5"),
    ("TwinSameSheet", "B5"),
    ("TwinSameSheet", "C5"),
    ("TwinSameSheet", "A6"),
    ("TwinSameSheet", "B6"),
    ("TwinSameSheet", "C6"),
)

#: The context experiments. This is the point of the fixture: an explicit map
#: from a sheet to the shapes its boundaries must survive.
BOUNDARY_EXPECTATIONS: Mapping[str, Any] = {
    "SingleTable": {
        "blocks": 1,
        "shape": "single continuous table",
        "expectation": "one region; address is a sufficient identity because "
                       "nothing else in the sheet looks like a table",
    },
    "TwoAdjacentTables": {
        "blocks": 1,
        "shape": "two tables stacked with no separating blank row and a changed "
                 "column structure (3 columns then 2)",
        "expectation": "the detector should not see a row gap, so it emits ONE "
                       "region spanning both tables and the region bounds do not "
                       "correspond to either real table",
    },
    "BlankSeparated": {
        "blocks": 2,
        "shape": "two tables separated by exactly one blank row",
        "expectation": "split at gap_tolerance=0; merged at gap_tolerance>=1",
    },
    "MergedCells": {
        "blocks": 1,
        "shape": "merged title A1:C1 and merged row label A2:A3",
        "expectation": "merge ranges are read; covered addresses are reported as "
                       "merge-covered rather than absent",
    },
    "RaggedRows": {
        "blocks": 1,
        "shape": "row 2 is short of the region width",
        "expectation": "ragged row detection; B2 empty, C2 absent",
    },
    "HiddenAxes": {
        "blocks": 2,
        "shape": "column C hidden and row 4 hidden; two stacked tables",
        "expectation": "hidden axes are reported per address; the two tables "
                       "differ in column width (3 then 2), so their bounds differ",
    },
    "DuplicateHeaders": {
        "blocks": 2,
        "shape": "two tables with identical header VALUES (Port, 2023, 2024) but "
                 "in different column order in the second table",
        "expectation": "header values alone cannot separate the tables by "
                       "position; only the range can",
    },
    "TwinSameSheet": {
        "blocks": 2,
        "shape": "two tables with byte-identical content at different addresses "
                 "in the same sheet",
        "expectation": "the strongest ambiguity case: header values identical, "
                       "content fingerprint identical, only the address differs",
    },
    "SideBySide": {
        "blocks": 1,
        "shape": "two tables on the same rows, in different column ranges",
        "expectation": "KNOWN LIMITATION: the detector groups by row, so two "
                       "side-by-side tables become one region spanning both, "
                       "with the blank separator reported as an empty column",
    },
    "DeclaredAgrees": {
        "blocks": 1,
        "shape": "one region plus one declared OOXML table object (A1:C3)",
        "expectation": "declared and inferred must AGREE on range, header row, "
                       "column count and column names",
    },
    "DeclaredTwins": {
        "blocks": 2,
        "shape": "two byte-identical tables that are each declared by name",
        "expectation": "inference produces two identical contexts, but the "
                       "workbook declares DeclaredTwinFirst (A1:C3) and "
                       "DeclaredTwinSecond (A7:C9); each inferred region must "
                       "match its own declared table, which is the case "
                       "inference alone cannot decide",
    },
    "DeclaredMismatch": {
        "blocks": 1,
        "shape": "declared range A1:C5 but only A1:C3 is populated",
        "expectation": "DISAGREEMENT on range_end (declared C5 vs inferred C3), "
                       "reported as a disagreement rather than as 'no declared "
                       "table found'",
    },
}


def build_spec() -> xlsx_writer.XlsxSpec:
    return xlsx_writer.XlsxSpec(sheets=SHEETS, shared_strings=SHARED_STRINGS)


def build_parts() -> dict[str, bytes]:
    return xlsx_writer.build_parts(build_spec())


def build_workbook_bytes() -> bytes:
    return xlsx_writer.build_workbook_bytes(build_spec())


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_manifest(digest: str, size: int) -> dict[str, Any]:
    return {
        "schema_version": "seaflow-v2.1.1-fixture-manifest/v1",
        "phase": "V2.1.1-TABLE-IDENTITY",
        "fixture": FIXTURE_NAME,
        "sha256": digest,
        "bytes": size,
        "determinism": {
            "zip_member_timestamps": "pinned to 1980-01-01T00:00:00",
            "part_order": "fixed by xlsx_writer.build_parts()",
            "shared_string_order": "fixed by SHARED_STRINGS",
            "writer": "fixtures/xlsx_writer.py (shared with the V2.1 fixture)",
        },
        "sheets": [
            {
                "name": sheet.name,
                "index": index,
                "declared_rows": len(sheet.rows),
                "hidden_rows": list(sheet.hidden_rows),
                "hidden_columns": [
                    list(range(c.min_index, c.max_index + 1))
                    for c in sheet.columns
                    if c.hidden
                ],
                "merged_ranges": list(sheet.merged_ranges),
            }
            for index, sheet in enumerate(SHEETS, start=1)
        ],
        "boundary_expectations": BOUNDARY_EXPECTATIONS,
        "truth": TRUTH_NAME,
        "generated_by": "fixtures/build_table_context_fixture.py",
    }


def build_truth(digest: str) -> dict[str, Any]:
    return {
        "schema_version": "seaflow-v2.1.1-table-context-truth/v1",
        "fixture": FIXTURE_NAME,
        "fixture_sha256": digest,
        "provisional": True,
        "sheets": [sheet.name for sheet in SHEETS],
        "absent_coordinates": [
            {"sheet": sheet, "ref": ref} for sheet, ref in ABSENT_COORDINATES
        ],
        "boundary_expectations": BOUNDARY_EXPECTATIONS,
    }


def write_fixture(out_dir: Path | None = None, truth_dir: Path | None = None) -> dict[str, Any]:
    out_dir = Path(out_dir or GENERATED_DIR)
    truth_dir = Path(truth_dir or TRUTH_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    payload = build_workbook_bytes()
    digest = _sha256(payload)
    (out_dir / FIXTURE_NAME).write_bytes(payload)

    (truth_dir / TRUTH_NAME).write_text(
        json.dumps(build_truth(digest), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
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
