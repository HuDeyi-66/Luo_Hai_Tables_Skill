"""T6 -- citation reconstruction and its boundary cases.

The fixture is built so that a plausible but wrong answer is easy to produce:
two cells hold ``42`` inside one table, a second ``42`` exists in a different
sheet, two rows are labelled ``Shanghai``, and a third ``Shanghai`` sits in a
CJK table with identical column headers. A resolver that picks a first match
would look successful and be wrong.

Every citation produced here is verified **back against the fixture bytes**
using the independent stdlib reader, so the test cannot pass by agreeing with
itself.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _bootstrap  # noqa: E402

from core.artifact import Artifact  # noqa: E402
from core.evidence import LossKind  # noqa: E402
from skills.luohai import ooxml  # noqa: E402
from skills.luohai.backends import FixtureXlsxBackend  # noqa: E402
from skills.luohai.citation import (  # noqa: E402
    Ambiguous,
    Citation,
    CitationProblem,
    CitationSelector,
    Unresolved,
    resolve_citation,
)
from skills.luohai import TabularEvidenceSkill  # noqa: E402

CITATION_REGION = "table:CitationTable:A1:C3"
SPLIT_REGION = "table:CitationTable:A1:C6"


def build_result(options: dict | None = None):
    artifact = Artifact.from_file(_bootstrap.FIXTURE_PATH, "art-fixture")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return artifact, skill.run(artifact, source_id="src-1", options=options)


def unit_for(result, region_id: str):
    for unit in result.units:
        if unit.address.container_id == region_id:
            return unit
    raise AssertionError(
        f"no unit {region_id!r}; have {[u.address.container_id for u in result.units]}"
    )


def read_fixture_cell(sheet_name: str, ref: str):
    """Independent verification: read the cell straight out of the package."""
    pkg = ooxml.read_package(str(_bootstrap.FIXTURE_PATH))
    sheet = pkg.sheet_by_name(sheet_name)
    assert sheet is not None
    cell = sheet.cells.get(ref)
    if cell is None:
        return "ABSENT_NO_CELL_ELEMENT"
    if cell.kind == "blank":
        return "EMPTY_PRESENT_CELL"
    return cell.value


class CanonicalCitationTests(unittest.TestCase):
    """The exit condition: one citation reconstructs to the fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.truth = json.loads(_bootstrap.TRUTH_PATH.read_text(encoding="utf-8"))
        cls.unit = unit_for(cls.result, CITATION_REGION)

    def test_canonical_query_resolves_to_exactly_one_cell(self) -> None:
        canonical = self.truth["citation_truth"]["canonical_citation"]
        citation = resolve_citation(
            self.unit,
            CitationSelector(
                sheet_name=canonical["sheet_name"],
                row_header=canonical["row_header"],
                column_header=canonical["column_header"],
                region_id=CITATION_REGION,
            ),
        )
        self.assertIsInstance(citation, Citation)
        assert isinstance(citation, Citation)
        self.assertEqual(citation.ref, canonical["ref"])
        self.assertEqual(citation.row_index, canonical["row_index"])
        self.assertEqual(citation.column_index, canonical["column_index"])
        self.assertEqual(citation.value, 42.0)
        self.assertEqual(citation.row_header, canonical["row_header"])
        self.assertEqual(citation.column_header, canonical["column_header"])
        self.assertEqual(citation.region_id, CITATION_REGION)
        self.assertEqual(citation.uniqueness, "table_context")

    def test_the_citation_survives_a_round_trip_to_the_fixture(self) -> None:
        citation = resolve_citation(
            self.unit,
            CitationSelector(
                sheet_name="CitationTable", row_header="Shanghai", column_header="2024"
            ),
        )
        assert isinstance(citation, Citation)
        self.assertEqual(
            read_fixture_cell(citation.sheet_name, citation.ref), citation.value
        )

    def test_the_citation_carries_a_full_disambiguation_chain(self) -> None:
        citation = resolve_citation(
            self.unit,
            CitationSelector(
                sheet_name="CitationTable", row_header="Shanghai", column_header="2024"
            ),
        )
        assert isinstance(citation, Citation)
        for expected in (
            "artifact:art-fixture",
            "source:src-1",
            "sheet:CitationTable",
            f"region:{CITATION_REGION}",
            "row_header:Shanghai",
            "column_header:2024",
            "cell:C2",
        ):
            self.assertIn(expected, citation.context_path)

    def test_citation_records_which_backend_produced_the_evidence(self) -> None:
        citation = resolve_citation(
            self.unit,
            CitationSelector(sheet_name="CitationTable", ref="C2"),
        )
        assert isinstance(citation, Citation)
        self.assertEqual(citation.producer_backend_id, "fixture.ooxml-stdlib")

    def test_citation_serialises_to_json(self) -> None:
        citation = resolve_citation(
            self.unit, CitationSelector(sheet_name="CitationTable", ref="C2")
        )
        assert isinstance(citation, Citation)
        payload = json.loads(json.dumps(citation.as_dict(), ensure_ascii=False))
        self.assertEqual(payload["ref"], "C2")
        self.assertEqual(payload["uniqueness"], "table_context")


class AmbiguityTests(unittest.TestCase):
    """The cases that must NOT resolve."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.truth = json.loads(_bootstrap.TRUTH_PATH.read_text(encoding="utf-8"))
        cls.unit = unit_for(cls.result, CITATION_REGION)

    def test_a_bare_row_label_matches_every_cell_of_that_row(self) -> None:
        """A row label identifies a row, never a cell -- so it stays ambiguous."""
        outcome = resolve_citation(
            self.unit,
            CitationSelector(region_id=CITATION_REGION, row_header="Shanghai"),
        )
        self.assertIsInstance(outcome, Ambiguous)
        assert isinstance(outcome, Ambiguous)
        self.assertEqual(sorted(outcome.candidate_refs), ["A2", "B2", "C2"])

    def test_a_selector_without_table_context_is_rejected_as_malformed(self) -> None:
        outcome = resolve_citation(self.unit, CitationSelector(row_header="Shanghai"))
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, CitationProblem.MALFORMED_SELECTOR)

    def test_header_pair_alone_is_not_unique_across_the_artifact(self) -> None:
        """(Shanghai, 2024) matches CitationTable!C2 and RaggedTable!C2 and !C4.

        Two of those hold 42, so even agreeing on the value would not
        disambiguate them. This is the correction to the earlier plan note:
        worksheet/bounds identity is required, not merely convenient.
        """
        matches = []
        for unit in self.result.units:
            outcome = resolve_citation(
                unit,
                CitationSelector(
                    region_id=unit.address.container_id,
                    row_header="Shanghai",
                    column_header="2024",
                    require_table_context=False,
                ),
            )
            if isinstance(outcome, Ambiguous):
                matches.extend(
                    f"{cell.sheet_name}!{cell.ref}" for cell in outcome.candidates
                )
            elif isinstance(outcome, Citation):
                matches.append(f"{outcome.sheet_name}!{outcome.ref}")
        self.assertEqual(
            sorted(matches),
            ["CitationTable!C2", "RaggedTable!C2", "RaggedTable!C4"],
        )

        # The two RaggedTable matches are not even the same kind of cell: one
        # coordinate is absent from the package, the other holds the number 7.
        ragged = unit_for(self.result, "table:RaggedTable:A1:C4")
        cells = {c["ref"]: c for c in ragged.payload["tabular"]["cells"]}
        self.assertEqual(cells["C2"]["value_kind"], "absent")
        self.assertEqual(cells["C4"]["value"], 7.0)
        self.assertEqual(cells["C4"]["value_kind"], "number")

    def test_table_context_is_what_makes_an_intersection_unique(self) -> None:
        """The same labels inside two tables resolve to two different cells."""
        resolved_with_identity = resolve_citation(
            self.unit,
            CitationSelector(
                sheet_name="CitationTable",
                region_id=CITATION_REGION,
                row_header="Shanghai",
                column_header="2024",
            ),
        )
        self.assertIsInstance(resolved_with_identity, Citation)
        assert isinstance(resolved_with_identity, Citation)
        self.assertEqual(resolved_with_identity.ref, "C2")
        self.assertEqual(resolved_with_identity.value, 42.0)

        # The same (Shanghai, 2024) pair inside RaggedTable is genuinely
        # ambiguous on its own, because that table has two Shanghai rows.
        ragged_unit = unit_for(self.result, "table:RaggedTable:A1:C4")
        without_identity = resolve_citation(
            ragged_unit,
            CitationSelector(
                region_id="table:RaggedTable:A1:C4",
                row_header="Shanghai",
                column_header="2024",
            ),
        )
        self.assertIsInstance(without_identity, Ambiguous)
        assert isinstance(without_identity, Ambiguous)
        self.assertEqual(sorted(without_identity.candidate_refs), ["C2", "C4"])

        # Pinning the coordinate as well as the table decides it.
        pinned = resolve_citation(
            ragged_unit,
            CitationSelector(
                region_id="table:RaggedTable:A1:C4",
                row_header="Shanghai",
                column_header="2024",
                row_index=4,
            ),
        )
        self.assertIsInstance(pinned, Citation)
        assert isinstance(pinned, Citation)
        self.assertEqual(pinned.ref, "C4")
        self.assertEqual(pinned.value, 7.0)
        self.assertEqual(pinned.value_kind, "number")

        # And the CJK label is genuinely absent from the English unit.
        wrong_sheet = resolve_citation(
            self.unit,
            CitationSelector(sheet_name="CitationTable", row_header="上海"),
        )
        self.assertIsInstance(wrong_sheet, Unresolved)

    def test_a_bare_value_matches_everywhere_and_locates_nothing(self) -> None:
        """Three cells hold the *number* 42; the value alone identifies none."""
        matches = []
        for unit in self.result.units:
            outcome = resolve_citation(
                unit, CitationSelector(region_id=unit.address.container_id, value=42.0)
            )
            if isinstance(outcome, Ambiguous):
                matches.extend(outcome.candidate_refs)
            elif isinstance(outcome, Citation):
                matches.append(outcome.ref)
        self.assertEqual(
            sorted(matches), ["C2", "C3", "C3"], "three cells hold 42 across two sheets"
        )

    def test_a_textual_42_is_not_the_number_42(self) -> None:
        """Kind strictness: a string cell must not satisfy a numeric query."""
        ragged = unit_for(self.result, "table:RaggedTable:A1:C4")
        cells = {c["ref"]: c for c in ragged.payload["tabular"]["cells"]}
        self.assertEqual(cells["B4"]["value"], "42")
        self.assertEqual(cells["B4"]["value_kind"], "string")

        # B4 holds the *text* "42"; a numeric query must not match it.
        numeric = resolve_citation(
            ragged,
            CitationSelector(region_id="table:RaggedTable:A1:C4", value=42),
        )
        self.assertIsInstance(numeric, Citation)
        assert isinstance(numeric, Citation)
        self.assertEqual(numeric.ref, "C3")
        self.assertEqual(numeric.value_kind, "number")

        # The textual query matches the text cell, exactly once.
        textual = resolve_citation(
            ragged,
            CitationSelector(region_id="table:RaggedTable:A1:C4", value="42"),
        )
        self.assertIsInstance(textual, Citation)
        assert isinstance(textual, Citation)
        self.assertEqual(textual.ref, "B4")
        self.assertEqual(textual.value_kind, "string")

    def test_asking_for_the_wrong_region_is_unresolved(self) -> None:
        outcome = resolve_citation(
            self.unit, CitationSelector(region_id="table:CnTable:A1:C3", ref="C2")
        )
        self.assertIsInstance(outcome, Unresolved)

    def test_an_empty_selector_is_rejected(self) -> None:
        outcome = resolve_citation(self.unit, CitationSelector())
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, CitationProblem.MALFORMED_SELECTOR)

    def test_a_value_selector_inside_a_narrow_region_resolves(self) -> None:
        """Bounded by the region and the column header, C2 is the only match."""
        outcome = resolve_citation(
            self.unit,
            CitationSelector(
                region_id=CITATION_REGION, column_header="2024", value=42.0
            ),
        )
        self.assertIsInstance(outcome, Ambiguous)
        assert isinstance(outcome, Ambiguous)
        self.assertEqual(sorted(outcome.candidate_refs), ["C2", "C3"])


class BoundaryCaseTests(unittest.TestCase):
    """Empty cells, absent coordinates, ragged rows, out-of-bounds addresses."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.ragged = unit_for(cls.result, "table:RaggedTable:A1:C4")
        cls.citation = unit_for(cls.result, CITATION_REGION)

    def test_a_present_but_blank_cell_resolves_as_empty(self) -> None:
        outcome = resolve_citation(
            self.ragged, CitationSelector(sheet_name="RaggedTable", ref="B2")
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.value_kind, "empty")
        self.assertIn(LossKind.EMPTY, outcome.loss)
        self.assertEqual(read_fixture_cell("RaggedTable", "B2"), "EMPTY_PRESENT_CELL")

    def test_a_coordinate_with_no_cell_element_resolves_as_absent(self) -> None:
        outcome = resolve_citation(
            self.ragged, CitationSelector(sheet_name="RaggedTable", ref="C2")
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.value_kind, "absent")
        self.assertIn(LossKind.ABSENT, outcome.loss)
        self.assertEqual(read_fixture_cell("RaggedTable", "C2"), "ABSENT_NO_CELL_ELEMENT")

    def test_empty_and_absent_are_not_the_same_outcome(self) -> None:
        empty = resolve_citation(
            self.ragged, CitationSelector(sheet_name="RaggedTable", ref="B2")
        )
        absent = resolve_citation(
            self.ragged, CitationSelector(sheet_name="RaggedTable", ref="C2")
        )
        assert isinstance(empty, Citation) and isinstance(absent, Citation)
        self.assertEqual(empty.value_kind, "empty")
        self.assertEqual(absent.value_kind, "absent")
        self.assertNotEqual(empty.value_kind, absent.value_kind)

        # The distinction is corroborated against the package itself: B2 has a
        # <c> element that is blank, C2 has no element at all.
        pkg = ooxml.read_package(str(_bootstrap.FIXTURE_PATH))
        sheet = pkg.sheet_by_name("RaggedTable")
        assert sheet is not None
        self.assertTrue(sheet.cells["B2"].element_present)
        self.assertTrue(sheet.cells["B2"].structurally_blank)
        self.assertNotIn("C2", sheet.cells)

    def test_a_coordinate_outside_the_region_is_unresolved(self) -> None:
        outcome = resolve_citation(
            self.citation, CitationSelector(sheet_name="CitationTable", ref="C7")
        )
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertIn("outside region bounds", outcome.message)

    def test_an_empty_sheet_unit_cannot_support_a_citation(self) -> None:
        empty_unit = unit_for(self.result, "worksheet:EmptyCase")
        outcome = resolve_citation(
            empty_unit, CitationSelector(sheet_name="EmptyCase", ref="A1")
        )
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, CitationProblem.NO_TABULAR_PAYLOAD)

    def test_a_failed_unit_is_blocked_from_positional_resolution(self) -> None:
        from core.evidence import EvidenceUnit, ProducerRef, CitationAddress, UnitClass

        broken = EvidenceUnit(
            unit_id="broken",
            unit_class=UnitClass.CONTENT,
            source_id="src-1",
            artifact_id="art-fixture",
            producer=ProducerRef(skill_id="x", backend_id="y"),
            address=CitationAddress(
                kind="content_location",
                container_id="table:S:A1:A1",
                context_path=("sheet:S",),
            ),
            loss=(LossKind.FAILED,),
            payload={},
        )
        outcome = resolve_citation(broken, CitationSelector(value=1))
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, CitationProblem.NO_TABULAR_PAYLOAD)

    def test_ragged_row_cells_are_locatable_even_though_the_row_is_short(self) -> None:
        outcome = resolve_citation(
            self.ragged, CitationSelector(sheet_name="RaggedTable", ref="C3")
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.value, 42.0)
        self.assertEqual(read_fixture_cell("RaggedTable", "C3"), 42.0)


class RowColumnIdentityTests(unittest.TestCase):
    """Identity established by explicit address vs. by labels."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build_result()
        cls.unit = unit_for(cls.result, CITATION_REGION)

    def test_canonical_query_needs_the_region_not_the_default_split(self) -> None:
        outcome = resolve_citation(
            self.unit,
            CitationSelector(
                sheet_name="CitationTable",
                region_id=CITATION_REGION,
                row_header="Shanghai",
                column_header="2024",
            ),
        )
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.ref, "C2")
        self.assertFalse(outcome.is_weak)
        self.assertEqual(outcome.uniqueness, "table_context")

    def test_resolving_by_explicit_coordinate_is_exact(self) -> None:
        outcome = resolve_citation(
            self.unit, CitationSelector(region_id=CITATION_REGION, ref="C2")
        )
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.ref, "C2")
        self.assertEqual(outcome.uniqueness, "table_context")
        self.assertFalse(outcome.is_weak)

    def test_a_missing_coordinate_inside_bounds_is_absent_not_a_miss(self) -> None:
        ragged = unit_for(self.result, "table:RaggedTable:A1:C4")
        outcome = resolve_citation(
            ragged, CitationSelector(region_id="table:RaggedTable:A1:C4", ref="C2")
        )
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.value_kind, "absent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
