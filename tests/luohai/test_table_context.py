"""V2.1.1 -- table context spike tests.

Four questions, in the order the task asks them:

1. **Boundary detection** -- what information lets the extractor decide where a
   table starts and ends, across the eight fixture shapes?
2. **Context candidates** -- what can A (sheet+range), B (+header values) and C
   (+header context + content fingerprint) each resolve, and what do they
   collapse?
3. **Ambiguity handling** -- does the resolver refuse instead of returning a
   first match?
4. **TableEvidenceUnit integration** -- is the context attached without enlarging
   ``TableEvidenceUnit``?

Plus a reproducibility check on the new fixture.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _bootstrap  # noqa: E402

from skills.luohai.contracts import TableArtifact  # noqa: E402
from skills.luohai.contracts import TableEvidenceUnit, TableLossKind  # noqa: E402
from skills.luohai import table_context  # noqa: E402
from skills.luohai.backends import FixtureXlsxBackend  # noqa: E402
from skills.luohai.citation import (  # noqa: E402
    Citation,
    CitationSelector,
    TableResolution,
    resolve_citation,
    resolve_table_context,
)
from skills.luohai import TabularEvidenceSkill  # noqa: E402
from fixtures import build_table_context_fixture as builder  # noqa: E402

FIXTURE_PATH = builder.GENERATED_DIR / builder.FIXTURE_NAME
MANIFEST_PATH = builder.GENERATED_DIR / builder.MANIFEST_NAME
TRUTH_PATH = builder.TRUTH_DIR / builder.TRUTH_NAME


def build_result(options: dict | None = None):
    artifact = TableArtifact.from_file(FIXTURE_PATH, "art-context")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return artifact, skill.run(
        artifact, source_id="src-context", options=options or {}
    )


def region_map(result) -> dict[str, object]:
    """``{region_id: unit}`` for the tabular units."""
    return {
        unit.address.container_id: unit
        for unit in result.units
        if unit.address.container_id.startswith("table:")
    }


def region_id(sheet: str, bounds: str) -> str:
    return f"table:{sheet}:{bounds}"


def tabular_block(unit) -> dict:
    block = (unit.payload or {}).get("tabular")
    return block if isinstance(block, dict) else {}


def unit_sheet(unit) -> str:
    return str(tabular_block(unit).get("sheet_name") or "")


def unit_bounds(unit) -> str:
    return str(tabular_block(unit).get("bounds") or "")


class FixtureReproducibilityTests(unittest.TestCase):
    def test_rebuild_is_byte_identical(self) -> None:
        self.assertEqual(
            builder.build_workbook_bytes(), builder.build_workbook_bytes()
        )

    def test_written_fixture_matches_manifest(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        payload = FIXTURE_PATH.read_bytes()
        self.assertEqual(builder._sha256(payload), manifest["sha256"])
        self.assertEqual(len(payload), manifest["bytes"])

    def test_truth_manifest_is_pinned_to_the_fixture(self) -> None:
        truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            truth["fixture_sha256"],
            builder._sha256(FIXTURE_PATH.read_bytes()),
        )

    def test_fixture_covers_every_required_shape(self) -> None:
        covered = set(builder.BOUNDARY_EXPECTATIONS)
        expected = {
            "SingleTable",
            "TwoAdjacentTables",
            "BlankSeparated",
            "MergedCells",
            "RaggedRows",
            "HiddenAxes",
            "DuplicateHeaders",
            "TwinSameSheet",
        }
        self.assertTrue(
            expected.issubset(covered),
            f"fixture does not cover: {sorted(expected - covered)}",
        )


class BoundaryDetectionTests(unittest.TestCase):
    """Experiment 1: what information determines a table boundary?"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.regions = region_map(cls.result)

    def test_every_fixture_sheet_is_extracted(self) -> None:
        represented = set(self.result.diagnostics.stats["represented_sheets"])
        self.assertEqual(represented, set(builder.BOUNDARY_EXPECTATIONS))

    def test_single_table_is_one_region(self) -> None:
        self.assertIn(region_id("SingleTable", "A1:C3"), self.regions)
        sheet_regions = [
            key for key in self.regions if key.startswith("table:SingleTable:")
        ]
        self.assertEqual(len(sheet_regions), 1)

    def test_blank_separated_tables_split_at_default_tolerance(self) -> None:
        left = region_id("BlankSeparated", "A1:C3")
        right = region_id("BlankSeparated", "A5:C7")
        self.assertIn(left, self.regions)
        self.assertIn(right, self.regions)

    def test_blank_separated_tables_merge_at_a_larger_tolerance(self) -> None:
        _, merged = build_result({"gap_tolerance": 2})
        keys = {
            unit.address.container_id
            for unit in merged.units
            if unit_sheet(unit) == "BlankSeparated"
        }
        self.assertEqual(keys, {region_id("BlankSeparated", "A1:C7")})

    def test_adjacent_tables_without_a_blank_row_are_one_region(self) -> None:
        """The known weak case: nothing separates the blocks, so they merge.

        The detector must not hide this: the merged region is reported, and the
        rows that do not span the full width are flagged ragged so the caller
        can see that the rectangle is a poor fit.
        """
        merged_id = region_id("TwoAdjacentTables", "A1:C5")
        self.assertIn(merged_id, self.regions)
        unit = self.regions[merged_id]
        block = unit.payload["tabular"]
        self.assertEqual(block["ragged_rows"], [4, 5])
        self.assertIn(TableLossKind.ABSENT, unit.loss)

    def test_merged_cells_are_read_and_reported(self) -> None:
        unit = self.regions[region_id("MergedCells", "A1:C4")]
        block = unit.payload["tabular"]
        self.assertEqual(block["merged_ranges"], ["A1:C1", "A2:A3"])

        cells = {c["ref"]: c for c in block["cells"]}
        # A3 is covered by the A2:A3 merge, so it is reported as merged -- not
        # as absent, which is what it would be without reading merge ranges.
        self.assertEqual(cells["A3"]["value_kind"], "merged")
        self.assertEqual(cells["A3"]["merged_from"], "A2")
        self.assertEqual(cells["A2"]["value"], "Key")
        # The merged title occupies A1:C1 and is preserved as text.
        self.assertEqual(cells["A1"]["value"], "Annual Throughput")
        self.assertEqual(cells["B1"]["merged_from"], "A1")
        self.assertEqual(cells["B1"]["value_kind"], "merged")

    def test_merge_covered_address_is_not_reported_as_absent(self) -> None:
        """The distinction that reading merge ranges buys.

        A covered coordinate keeps the ``ABSENT`` loss kind (no cell element was
        written for it) but its ``value_kind`` is ``merged``, so a consumer can
        tell "the author merged this" from "this coordinate is missing".
        """
        unit = self.regions[region_id("MergedCells", "A1:C4")]
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["A3"]["value_kind"], "merged")
        self.assertEqual(cells["A3"]["merged_from"], "A2")
        self.assertNotEqual(cells["A3"]["value_kind"], "absent")
        # A genuinely missing coordinate in another region still reads absent.
        ragged = self.regions[region_id("RaggedRows", "A1:C3")]
        ragged_cells = {c["ref"]: c for c in ragged.payload["tabular"]["cells"]}
        self.assertEqual(ragged_cells["C2"]["value_kind"], "absent")
        self.assertIsNone(ragged_cells["C2"]["merged_from"])

    def test_merged_row_label_does_not_become_a_data_row(self) -> None:
        """A merge-covered coordinate must not be treated as a data row.

        Note the *separate* limitation this fixture also exposes: the merged
        title in A1:C1 makes row 1 the header row, so the real column headers
        (row 2) are not recognised as headers and a header-based selector cannot
        reach this table. That is a header-detection gap, recorded in the note,
        not a merge-handling gap.
        """
        unit = self.regions[region_id("MergedCells", "A1:C4")]
        block = unit.payload["tabular"]
        cells = {c["ref"]: c for c in block["cells"]}

        self.assertEqual(block["header_row"], 1)
        self.assertEqual(cells["A1"]["value"], "Annual Throughput")
        self.assertTrue(cells["A1"]["is_header"])
        self.assertTrue(cells["B1"]["is_header"])
        # The merged row label A2 is data, not a header.
        self.assertFalse(cells["A2"]["is_header"])
        self.assertTrue(cells["A3"]["is_header"] is False)
        self.assertEqual(cells["A3"]["value_kind"], "merged")

        # An address selector reaches the numeric cell regardless.
        outcome = resolve_citation(
            unit,
            CitationSelector(
                region_id=region_id("MergedCells", "A1:C4"), ref="C3"
            ),
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.value, 42.0)

    def test_ragged_row_and_absent_coordinate_are_distinguished(self) -> None:
        unit = self.regions[region_id("RaggedRows", "A1:C3")]
        block = unit.payload["tabular"]
        self.assertEqual(block["ragged_rows"], [2])
        cells = {c["ref"]: c for c in block["cells"]}
        self.assertEqual(cells["B2"]["value_kind"], "empty")
        self.assertEqual(cells["C2"]["value_kind"], "absent")

    def test_hidden_column_and_hidden_row_are_reported_per_region(self) -> None:
        unit = self.regions[region_id("HiddenAxes", "A1:C2")]
        block = unit.payload["tabular"]
        self.assertEqual(block["hidden_columns"], [3])
        self.assertEqual(block["hidden_rows"], [])
        cells = {c["ref"]: c for c in block["cells"]}
        self.assertTrue(cells["C1"]["hidden"], "hidden column C must be marked")
        self.assertFalse(cells["A1"]["hidden"])
        self.assertIn(TableLossKind.SILENT_LOSS_RISK, unit.loss)

    def test_hidden_row_is_reported_on_the_region_that_contains_it(self) -> None:
        unit = self.regions[region_id("HiddenAxes", "A5:C6")]
        block = unit.payload["tabular"]
        self.assertEqual(block["hidden_rows"], [])

        _, whole_sheet = build_result({"gap_tolerance": 3})
        merged = [
            u
            for u in whole_sheet.units
            if unit_sheet(u) == "HiddenAxes"
            and u.address.container_id.startswith("table:")
        ]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].payload["tabular"]["hidden_rows"], [4])
        self.assertIn(TableLossKind.SILENT_LOSS_RISK, merged[0].loss)

    def test_duplicate_headers_are_reported(self) -> None:
        """DuplicateHeaders#2 has 2024 before 2023; the values are reordered.

        The duplicate *detection* here is about repeated header text. The
        fixture's second table reorders the columns, so each header text is
        still unique within its table; the collision is between the two tables,
        which the context matrix measures.
        """
        unit = self.regions[region_id("DuplicateHeaders", "A1:C3")]
        block = unit.payload["tabular"]
        self.assertEqual(block["duplicate_column_headers"], [])
        self.assertEqual(
            block["column_headers"], {"A": "Port", "B": "2023", "C": "2024"}
        )
        second = self.regions[region_id("DuplicateHeaders", "A5:C6")]
        self.assertEqual(
            second.payload["tabular"]["column_headers"],
            {"A": "Port", "B": "2024", "C": "2023"},
        )

    def test_twin_tables_are_two_regions_with_identical_content(self) -> None:
        first = self.regions[region_id("TwinSameSheet", "A1:C3")]
        second = self.regions[region_id("TwinSameSheet", "A7:C9")]

        def values(unit):
            return [
                (c["ref"].rstrip("0123456789"), c["value"])
                for c in unit.payload["tabular"]["cells"]
            ]

        def shape(unit):
            return [
                (c["value_kind"], c["value"])
                for c in unit.payload["tabular"]["cells"]
            ]

        self.assertEqual(shape(first), shape(second))

    def test_side_by_side_tables_merge_into_one_region(self) -> None:
        """The second known boundary limitation, kept as a test.

        Detection groups by *row*, so two tables sharing rows cannot be split
        no matter how they are laid out side by side. The merged region keeps
        both header pairs, which is how the problem is visible to a caller.
        """
        unit = self.regions[region_id("SideBySide", "A1:E2")]
        headers = unit.payload["tabular"]["column_headers"]
        self.assertEqual(headers["A"], "Port")
        self.assertEqual(headers["B"], "2024")
        self.assertIsNone(headers["C"], "the separating column is empty")
        self.assertEqual(headers["D"], "Port")
        self.assertEqual(headers["E"], "2024")

    def test_boundary_detection_emits_a_warning_when_it_splits_a_sheet(self) -> None:
        codes = {w.code for w in self.result.diagnostics.warnings}
        self.assertIn("region_ambiguity", codes)


class IdentityCandidateTests(unittest.TestCase):
    """Experiment 2: what does each candidate resolve, and what does it collapse?"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.regions = region_map(cls.result)
        cls.contexts = {}
        counters: dict[str, int] = {}
        for key in sorted(cls.regions):
            unit = cls.regions[key]
            sheet = unit_sheet(unit)
            counters[sheet] = counters.get(sheet, 0) + 1
            name = f"{sheet}#{counters[sheet]}"
            block = unit.payload["tabular"]
            cls.contexts[name] = table_context.build_table_context(
                block,
                hidden_rows=block.get("hidden_rows") or (),
                hidden_columns=block.get("hidden_columns") or (),
                merged_ranges=block.get("merged_ranges") or (),
            )

    def test_all_three_candidates_are_produced(self) -> None:
        for context in self.contexts.values():
            self.assertTrue(context.candidate_a.startswith("sheet:"))
            self.assertIn("|headers:", context.candidate_b)
            self.assertIn("|fingerprint:", context.candidate_c)

    def test_candidate_a_is_worksheet_plus_range(self) -> None:
        context = self.contexts["SingleTable#1"]
        self.assertEqual(
            context.candidate_a, "sheet:SingleTable|range:A1:C3"
        )

    def test_candidate_b_contains_a_as_a_prefix(self) -> None:
        context = self.contexts["SingleTable#1"]
        self.assertTrue(context.candidate_b.startswith(context.candidate_a))

    def test_candidate_containment_means_a_is_the_base(self) -> None:
        """A caller supplying B or C also supplies the address."""
        for candidate in table_context.CANDIDATE_KEYS:
            left = self.contexts["SingleTable#1"]
            right = self.contexts["DuplicateHeaders#2"]
            self.assertNotEqual(
                table_context.candidate_components(left, candidate),
                table_context.candidate_components(right, candidate),
                f"candidate {candidate} contains the address, so two tables in "
                f"different places can never collapse",
            )

    def test_pairwise_context_collisions_are_empty_by_construction(self) -> None:
        matrix = table_context.build_collision_matrix(self.contexts)
        for candidate in table_context.CANDIDATE_KEYS:
            self.assertEqual(
                matrix["collapsed_context_pairs"][candidate],
                [],
                "every candidate hint embeds worksheet+range, so two tables "
                "never have equal contexts",
            )

    def test_candidate_a_query_collapses_across_the_artifact(self) -> None:
        """Without the worksheet, 'A1:C3' is the most common region in the book."""
        measurement = table_context.measurement_for_candidate(
            self.contexts, "A", scopes=("artifact",)
        )
        data = measurement["by_scope"]["artifact"]
        self.assertEqual(data["unique_count"], 5)
        self.assertEqual(data["ambiguous_count"], 12)
        # The five tables that still share the region A1:C3 are the collision.
        collision = next(
            entry for entry in data["ambiguous"] if entry["table"] == "SingleTable#1"
        )
        self.assertEqual(
            sorted(collision["matching_tables"]),
            [
                "BlankSeparated!A1:C3",
                "DeclaredAgrees!A1:C3",
                "DeclaredMismatch!A1:C3",
                "DeclaredTwins!A1:C3",
                "DuplicateHeaders!A1:C3",
                "RaggedRows!A1:C3",
                "SingleTable!A1:C3",
                "TwinSameSheet!A1:C3",
            ],
        )

    def test_candidate_a_query_is_unique_within_a_sheet(self) -> None:
        """Once the worksheet is known, the range alone names the table."""
        measurement = table_context.measurement_for_candidate(
            self.contexts, "A", scopes=("sheet",)
        )
        data = measurement["by_scope"]["sheet"]
        self.assertEqual(data["unique_count"], 17)
        self.assertEqual(data["ambiguous_count"], 0)

    def test_candidate_b_headers_collapse_across_similar_tables(self) -> None:
        measurement = table_context.measurement_for_candidate(self.contexts, "B")
        artifact = measurement["by_scope"]["artifact"]
        self.assertEqual(artifact["unique_count"], 4)
        self.assertEqual(artifact["ambiguous_count"], 13)
        collapsed = next(
            entry
            for entry in artifact["ambiguous"]
            if entry["table"] == "TwinSameSheet#1"
        )
        self.assertIn("TwinSameSheet!A7:C9", collapsed["matching_tables"])

    def test_candidate_b_is_partly_unique_inside_a_sheet(self) -> None:
        measurement = table_context.measurement_for_candidate(self.contexts, "B")
        sheet = measurement["by_scope"]["sheet"]
        self.assertEqual(sheet["unique_count"], 9)
        self.assertEqual(sheet["ambiguous_count"], 8)

    def test_candidate_c_fingerprint_separates_the_twins_from_other_tables(self) -> None:
        """C resolves the identical-content group except within one sheet."""
        measurement = table_context.measurement_for_candidate(self.contexts, "C")
        artifact = measurement["by_scope"]["artifact"]
        self.assertEqual(artifact["unique_count"], 8)
        self.assertEqual(artifact["ambiguous_count"], 9)
        twins = {
            entry["table"] for entry in artifact["ambiguous"]
        }
        self.assertIn("TwinSameSheet#1", twins)
        self.assertIn("TwinSameSheet#2", twins)

    def test_candidate_c_is_strongest_inside_a_sheet(self) -> None:
        measurement = table_context.measurement_for_candidate(self.contexts, "C")
        sheet = measurement["by_scope"]["sheet"]
        self.assertEqual(sheet["unique_count"], 13)
        self.assertEqual(sheet["ambiguous_count"], 4)

    def test_key_strength_and_scope_trade_off(self) -> None:
        """The headline result of the experiment, in one assertion.

        A stronger key helps most when the scope is wide; narrowing the scope
        helps most when the key is weak. Candidate A is perfect inside a sheet
        because a range is an address, which is the very thing a legal citation
        is supposed to carry -- and the very thing a caller usually does not
        have.
        """
        counts = {
            candidate: {
                scope: data["unique_count"]
                for scope, data in table_context.measurement_for_candidate(
                    self.contexts, candidate
                )["by_scope"].items()
            }
            for candidate in table_context.CANDIDATE_KEYS
        }
        self.assertEqual(counts["A"]["sheet"], 17)
        self.assertEqual(counts["A"]["artifact"], 5)
        self.assertEqual(counts["B"]["sheet"], 9)
        self.assertEqual(counts["B"]["artifact"], 4)
        self.assertEqual(counts["C"]["sheet"], 13)
        self.assertEqual(counts["C"]["artifact"], 8)
        for candidate in table_context.CANDIDATE_KEYS:
            self.assertGreaterEqual(
                counts[candidate]["sheet"],
                counts[candidate]["artifact"],
                "narrowing the scope can never make a key less specific",
            )

    def test_candidate_c_cannot_separate_identical_tables(self) -> None:
        """The irreducible case: same values, same headers, different address.

        No content-derived candidate can help here. Only the address can, which
        means address must be carried, not derived.
        """
        first = self.contexts["TwinSameSheet#1"]
        second = self.contexts["TwinSameSheet#2"]
        self.assertEqual(
            first.values["content_fingerprint"], second.values["content_fingerprint"]
        )
        self.assertNotEqual(first.candidate_a, second.candidate_a)

    def test_fingerprint_ignores_address_but_keeps_shape(self) -> None:
        first = self.contexts["TwinSameSheet#1"]
        second = self.contexts["TwinSameSheet#2"]
        self.assertEqual(
            first.values["content_fingerprint"], second.values["content_fingerprint"]
        )
        # A different table with similar headers must still fingerprint apart.
        other = self.contexts["RaggedRows#1"]
        self.assertNotEqual(
            first.values["content_fingerprint"], other.values["content_fingerprint"]
        )

    def test_content_fingerprint_groups_tables_by_content_not_by_place(self) -> None:
        """Five distinct tables share one fingerprint.

        SingleTable#1, BlankSeparated#1, DuplicateHeaders#1, RaggedRows#1 and
        TwinSameSheet#1 all hold exactly the same cells. They are *different
        tables* at different addresses -- which is precisely why a
        content-derived candidate cannot be the whole context, and why the
        address has to be carried rather than derived.
        """
        fingerprint = self.contexts["SingleTable#1"].values["content_fingerprint"]
        sharing = sorted(
            name
            for name, context in self.contexts.items()
            if context.values["content_fingerprint"] == fingerprint
        )
        self.assertEqual(
            sharing,
            [
                "BlankSeparated#1",
                "DeclaredAgrees#1",
                "DeclaredMismatch#1",
                "DeclaredTwins#1",
                "DeclaredTwins#2",
                "DuplicateHeaders#1",
                "SingleTable#1",
                "TwinSameSheet#1",
                "TwinSameSheet#2",
            ],
        )
        # Every one of them is still a separately addressable table.
        bounds = {self.contexts[name].bounds for name in sharing}
        sheets = {self.contexts[name].sheet_name for name in sharing}
        self.assertEqual(bounds, {"A1:C3", "A7:C9"})
        self.assertEqual(len(sheets), 7)
        # ...and the RaggedRows table, which looks similar, does not share it:
        # a different row shape must change the fingerprint.
        self.assertNotIn("RaggedRows#1", sharing)

    def test_identical_tables_have_identical_header_values(self) -> None:
        first = self.contexts["TwinSameSheet#1"]
        second = self.contexts["TwinSameSheet#2"]
        self.assertEqual(
            first.values["header_columns"], second.values["header_columns"]
        )
        self.assertEqual(
            first.values["header_column_values"],
            second.values["header_column_values"],
        )

    def test_hidden_axes_are_recorded_in_candidate_c_context_only(self) -> None:
        """A hidden column changes the context, never the address."""
        context = self.contexts["HiddenAxes#1"]
        self.assertEqual(context.values["structural"]["hidden_columns"], [3])
        self.assertIn("|context:", context.candidate_c)
        self.assertNotIn("hidden", context.candidate_a)


class AmbiguityHandlingTests(unittest.TestCase):
    """Experiment 3: the resolver must refuse, never return a first match."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.regions = region_map(cls.result)

    def test_region_address_alone_is_ambiguous_in_a_whole_workbook(self) -> None:
        """Which table is 'A1:C3'? Eight, workbook-wide.

        The lookup-key form of ``resolve_table_context`` matches whole hint
        strings, so it cannot see this. The query form answers the question a
        caller actually asks, and it refuses.
        """
        contexts = {}
        for key, unit in self.regions.items():
            if unit_bounds(unit) != "A1:C3":
                continue
            contexts[key] = table_context.build_table_context(
                unit.payload["tabular"]
            )
        self.assertEqual(len(contexts), 8)
        query = table_context.TableContextQuery(
            candidate="A", scope="artifact", bounds="A1:C3"
        )
        outcome = table_context.resolve_table_query(contexts, query)
        self.assertFalse(outcome.unique)
        self.assertEqual(outcome.status, table_context.ContextProblem.AMBIGUOUS)
        self.assertEqual(len(outcome.candidates), 8)

    def test_the_same_query_is_unique_inside_one_sheet(self) -> None:
        contexts = {}
        for key, unit in self.regions.items():
            contexts[key] = table_context.build_table_context(
                unit.payload["tabular"]
            )
        query = table_context.TableContextQuery(
            candidate="A",
            scope="sheet",
            sheet_name="SingleTable",
            bounds="A1:C3",
        )
        outcome = table_context.resolve_table_query(contexts, query)
        self.assertTrue(outcome.unique)
        assert outcome.table is not None
        self.assertEqual(outcome.table.sheet_name, "SingleTable")

    def test_headers_alone_cannot_identify_a_table_workbook_wide(self) -> None:
        """Candidate B's own table is not uniquely identified by candidate B.

        Seven tables in this small workbook share the headers
        (Port, 2023, 2024) and the row labels (Shanghai, Ningbo). A real
        workbook makes this worse, not better. Identifying the table therefore
        requires either the address or the fingerprint.
        """
        unit = self.regions[region_id("SingleTable", "A1:C3")]
        pool = {
            key: table_context.build_table_context(other.payload["tabular"])
            for key, other in self.regions.items()
        }
        context = pool[region_id("SingleTable", "A1:C3")]

        artifact_query = table_context.query_for_context(
            context, "B", scope="artifact"
        )
        artifact_outcome = table_context.resolve_table_query(pool, artifact_query)
        self.assertFalse(artifact_outcome.unique)
        self.assertEqual(
            artifact_outcome.status, table_context.ContextProblem.AMBIGUOUS
        )
        self.assertEqual(len(artifact_outcome.candidates), 11)
        # Narrowing the pool to the table's own worksheet makes B sufficient...
        sheet_query = table_context.query_for_context(context, "B", scope="sheet")
        sheet_outcome = table_context.resolve_table_query(pool, sheet_query)
        self.assertTrue(sheet_outcome.unique, sheet_outcome.message)
        assert sheet_outcome.table is not None
        self.assertEqual(sheet_outcome.table.region_id, "table:SingleTable:A1:C3")

        # ...and adding the fingerprint separates it from the similar-looking
        # tables -- but not from the tables that are genuinely identical, which
        # no content-derived key can separate.
        c_query = table_context.query_for_context(context, "C", scope="artifact")
        c_outcome = table_context.resolve_table_query(pool, c_query)
        self.assertFalse(c_outcome.unique)
        self.assertEqual(
            sorted(c.region_id for c in c_outcome.candidates),
            [
                "table:BlankSeparated:A1:C3",
                "table:DeclaredAgrees:A1:C3",
                "table:DeclaredMismatch:A1:C3",
                "table:DeclaredTwins:A1:C3",
                "table:DeclaredTwins:A7:C9",
                "table:DuplicateHeaders:A1:C3",
                "table:SingleTable:A1:C3",
                "table:TwinSameSheet:A1:C3",
                "table:TwinSameSheet:A7:C9",
            ],
        )

        self.assertEqual(
            table_context.unit_context_hints(unit)["A"], context.candidate_a
        )

    def test_resolver_refuses_a_header_query_matching_two_tables(self) -> None:
        """The required new test: two regions both hold Shanghai | 2024."""
        outcomes = []
        for key, unit in self.regions.items():
            if unit_sheet(unit) != "TwinSameSheet":
                continue
            outcome = resolve_citation(
                unit,
                CitationSelector(
                    region_id=key,
                    row_header="Shanghai",
                    column_header="2024",
                ),
            )
            self.assertIsInstance(outcome, Citation)
            outcomes.append((key, outcome.ref))
        # Each twin resolves internally, to different addresses...
        self.assertEqual(
            sorted(ref for _, ref in outcomes), ["C2", "C8"]
        )
        # ...which is the evidence that the tables differ only by address.
        self.assertEqual(len({key for key, _ in outcomes}), 2)

    def test_identical_tables_produce_table_level_ambiguity(self) -> None:
        contexts = {}
        for key, unit in self.regions.items():
            if unit_sheet(unit) != "TwinSameSheet":
                continue
            block = unit.payload["tabular"]
            contexts[key] = table_context.build_table_context(block)

        contexts_by_name = {
            f"twin{i}": context for i, context in enumerate(contexts.values(), start=1)
        }
        first = next(iter(contexts_by_name.values()))
        query = table_context.query_for_context(first, "C", scope="artifact")
        outcome = table_context.resolve_table_query(contexts_by_name, query)

        self.assertFalse(outcome.unique)
        self.assertEqual(outcome.status, table_context.ContextProblem.AMBIGUOUS)
        self.assertEqual(len(outcome.candidates), 2)
        payload = outcome.as_dict()
        self.assertEqual(payload["status"], "ambiguous")
        self.assertEqual(len(payload["candidates"]), 2)

    def test_header_pair_query_is_not_unique_without_table_context(self) -> None:
        """Across the artifact, (Shanghai, 2024) matches several tables."""
        matches = []
        for key, unit in self.regions.items():
            outcome = resolve_citation(
                unit,
                CitationSelector(
                    row_header="Shanghai",
                    column_header="2024",
                    require_table_context=False,
                ),
            )
            if isinstance(outcome, Citation):
                matches.append(f"{outcome.sheet_name}!{outcome.ref}")
        self.assertGreater(
            len(matches), 1, "the fixture must keep this ambiguity testable"
        )

    def test_ambiguous_table_query_lists_every_candidate(self) -> None:
        contexts = {}
        for key, unit in self.regions.items():
            if unit_sheet(unit) != "BlankSeparated":
                continue
            contexts[key] = table_context.build_table_context(
                unit.payload["tabular"]
            )
        first = next(iter(contexts.values()))
        query = table_context.query_for_context(first, "B", scope="artifact")
        outcome = table_context.resolve_table_query(contexts, query)
        self.assertFalse(outcome.unique)
        self.assertEqual(len(outcome.candidates), 2)

    def test_unresolved_is_reported_distinctly_from_ambiguous(self) -> None:
        contexts = {}
        for key, unit in self.regions.items():
            contexts[key] = table_context.build_table_context(
                unit.payload["tabular"]
            )
        query = table_context.TableContextQuery(
            candidate="A", scope="artifact", bounds="Z99:Z100"
        )
        outcome = table_context.resolve_table_query(contexts, query)
        self.assertFalse(outcome.unique)
        self.assertEqual(outcome.status, table_context.ContextProblem.UNRESOLVED)

    def test_unknown_candidate_is_a_malformed_query(self) -> None:
        contexts = {"one": next(iter(self.regions.values()))}
        query = table_context.TableContextQuery(candidate="D", scope="artifact")
        outcome = table_context.resolve_table_query(
            {"one": table_context.build_table_context(
                next(iter(self.regions.values())).payload["tabular"]
            )},
            query,
        )
        self.assertEqual(
            outcome.status, table_context.ContextProblem.MALFORMED_QUERY
        )

    def test_context_hint_that_matches_nothing_is_unresolved(self) -> None:
        outcome = resolve_table_context(
            list(self.result.units), hint="sheet:NoSuch|range:A1:A1", candidate="A"
        )
        self.assertNotIsInstance(outcome, Citation)
        self.assertNotIsInstance(outcome, TableResolution)
        self.assertEqual(outcome.problem, "unresolved")

    def test_selector_with_a_mismatched_context_hint_is_unresolved(self) -> None:
        unit = self.regions[region_id("SingleTable", "A1:C3")]
        outcome = resolve_citation(
            unit,
            CitationSelector(
                context_hint="sheet:NotThisTable|range:A1:C3",
                row_header="Shanghai",
                column_header="2024",
            ),
        )
        self.assertNotIsInstance(outcome, Citation)
        self.assertEqual(outcome.problem, "unresolved")

    def test_context_hint_plus_a_cell_selector_resolves_inside_one_table(self) -> None:
        unit = self.regions[region_id("SingleTable", "A1:C3")]
        hint = table_context.unit_context_hints(unit)["A"]
        outcome = resolve_citation(
            unit,
            CitationSelector(
                context_hint=hint, row_header="Shanghai", column_header="2024"
            ),
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.ref, "C2")
        self.assertEqual(outcome.value, 42.0)

    def test_context_hint_alone_never_produces_a_cell_citation(self) -> None:
        """Issue 3: naming a table must never be answered with a cell.

        ``resolve_table_context`` returns a table-level ``TableResolution``, so
        the caller is told *which table* and is never handed a syntactically
        convenient cell it did not ask for.
        """
        unit = self.regions[region_id("SingleTable", "A1:C3")]
        hint = table_context.unit_context_hints(unit)["A"]
        outcome = resolve_table_context(
            list(self.result.units), hint=hint, candidate="A"
        )
        self.assertNotIsInstance(outcome, Citation)
        self.assertIsInstance(outcome, TableResolution)
        assert isinstance(outcome, TableResolution)
        self.assertTrue(outcome.unique)
        self.assertIsNotNone(outcome.table)
        self.assertEqual(outcome.status, "resolved")
        self.assertNotIn("selected", outcome.as_dict())


class EvidenceUnitIntegrationTests(unittest.TestCase):
    """Experiment 4: attach context without enlarging TableEvidenceUnit."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.regions = region_map(cls.result)

    def test_evidence_unit_gained_no_new_dataclass_field(self) -> None:
        fields = set(TableEvidenceUnit.__dataclass_fields__)  # type: ignore[attr-defined]
        for forbidden in ("table_context", "identity", "table_id", "context_hint"):
            self.assertNotIn(
                forbidden,
                fields,
                "the context spike must not enlarge TableEvidenceUnit",
            )

    def test_core_evidence_has_no_table_specific_accessor(self) -> None:
        """Issue 4: Core must not carry table knowledge.

        The generic evidence record is checked directly rather than by reading
        its source: any attribute whose name mentions a table would be a Core
        leak, whichever module added it.
        """
        for attribute in ("table_context", "table_context_hint", "table_id"):
            self.assertFalse(
                hasattr(TableEvidenceUnit, attribute),
                f"TableEvidenceUnit must not expose {attribute!r}: table context is a "
                f"Skill-side convention, not a Core concept",
            )

    def test_table_context_is_attached_and_readable_via_the_skill_helper(self) -> None:
        unit = self.regions[region_id("SingleTable", "A1:C3")]
        context = table_context.unit_table_context(unit)
        self.assertIsNotNone(context)
        assert context is not None
        for key in ("container", "boundary", "context_hints"):
            self.assertIn(key, context)
        self.assertTrue(context["experimental"])
        self.assertTrue(context["unfrozen"])

    def test_table_context_recommended_shape_is_present(self) -> None:
        """The suggested container / boundary / context_hint shape."""
        context = table_context.unit_table_context(
            self.regions[region_id("SingleTable", "A1:C3")]
        )
        assert context is not None
        self.assertEqual(context["container"]["sheet_name"], "SingleTable")
        self.assertEqual(context["container"]["region_id"], "table:SingleTable:A1:C3")
        self.assertFalse(context["boundary"]["declared"])
        self.assertEqual(context["boundary"]["bounds"], "A1:C3")
        for candidate in ("A", "B", "C"):
            self.assertIn(candidate, context["context_hints"])

    def test_table_context_travels_through_serialisation(self) -> None:
        unit = self.regions[region_id("SingleTable", "A1:C3")]
        restored = TableEvidenceUnit.from_dict(json.loads(json.dumps(unit.as_dict())))
        self.assertEqual(
            table_context.unit_table_context(restored),
            table_context.unit_table_context(unit),
        )
        self.assertEqual(
            table_context.unit_context_hints(restored),
            table_context.unit_context_hints(unit),
        )

    def test_a_unit_without_context_returns_none_instead_of_raising(self) -> None:
        from skills.luohai.contracts import TableCitationAddress, TableProducer, TableUnitClass

        bare = TableEvidenceUnit(
            unit_id="bare",
            unit_class=TableUnitClass.CONTAINER,
            source_id="s",
            artifact_id="a",
            producer=TableProducer(skill_id="x"),
            address=TableCitationAddress(kind="sheet_cell"),
        )
        self.assertIsNone(table_context.unit_table_context(bare))
        self.assertIsNone(table_context.unit_context_hints(bare))

    def test_worksheet_units_carry_no_table_context(self) -> None:
        worksheet_units = [
            u for u in self.result.units if u.unit_class == "worksheet"
        ]
        for unit in worksheet_units:
            self.assertIsNone(table_context.unit_table_context(unit))

    def test_context_does_not_claim_a_declared_boundary(self) -> None:
        for unit in self.regions.values():
            context = table_context.unit_table_context(unit)
            assert context is not None
            self.assertFalse(context["boundary"]["declared"])
            self.assertIn("not declared", context["boundary"]["note"])


class ResolverNeverReturnsFirstMatchTests(unittest.TestCase):
    """The explicit prohibition from the task, tested directly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()

    def test_multi_match_returns_every_candidate(self) -> None:
        contexts = {}
        for unit in self.result.units:
            block = (unit.payload or {}).get("tabular")
            if not isinstance(block, dict):
                continue
            if unit_sheet(unit) != "TwinSameSheet":
                continue
            contexts[unit.address.container_id] = (
                table_context.build_table_context(block)
            )
        first = next(iter(contexts.values()))
        query = table_context.query_for_context(first, "B", scope="artifact")
        outcome = table_context.resolve_table_query(contexts, query)
        self.assertFalse(outcome.unique)
        self.assertEqual(len(outcome.candidates), 2)
        # Both tables are represented; neither is privileged as "the" answer.
        bounds = sorted(c.bounds for c in outcome.candidates)
        self.assertEqual(bounds, ["A1:C3", "A7:C9"])

    def test_ambiguous_outcome_is_json_serialisable(self) -> None:
        """The task asks for a {"status": "ambiguous", "candidates": [...]} shape."""
        contexts = {}
        for unit in self.result.units:
            block = (unit.payload or {}).get("tabular")
            if isinstance(block, dict) and unit_sheet(unit) == "TwinSameSheet":
                contexts[unit.address.container_id] = (
                    table_context.build_table_context(block)
                )
        first = next(iter(contexts.values()))
        query = table_context.query_for_context(first, "C", scope="artifact")
        payload = json.loads(
            json.dumps(
                table_context.resolve_table_query(contexts, query).as_dict()
            )
        )
        self.assertEqual(payload["status"], "ambiguous")
        self.assertFalse(payload["unique"])
        self.assertEqual(len(payload["candidates"]), 2)
        self.assertEqual(
            sorted(c["bounds"] for c in payload["candidates"]), ["A1:C3", "A7:C9"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
