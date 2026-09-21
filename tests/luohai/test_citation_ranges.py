"""V2.2 -- range location tests.

The V2.2 task requires cell *and range* location. Cell location was covered by
V2.1; ranges are new here, so they get their own file.

The governing rule: a range citation reports every coordinate in the rectangle,
including the empty, absent and merged ones. A range that cannot be described
completely is ``unresolved`` rather than partially satisfied, and a range
request is never quietly answered with a single cell.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import _bootstrap  # noqa: E402

from skills.luohai.contracts import TableArtifact  # noqa: E402
from skills.luohai.contracts import TableLossKind  # noqa: E402
from skills.luohai import (  # noqa: E402
    Ambiguous,
    Citation,
    CitationSelector,
    FixtureXlsxBackend,
    TabularEvidenceSkill,
    Unresolved,
    resolve_citation,
)
from skills.luohai.citation import RangeCitation  # noqa: E402

FIXTURE = _bootstrap.FIXTURE_PATH


def build():
    artifact = TableArtifact.from_file(FIXTURE, "art-fixture")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return artifact, skill.run(artifact, source_id="src-1")


def unit_for(result, container_id: str):
    return next(u for u in result.units if u.address.container_id == container_id)


class RangeResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()
        cls.citation = unit_for(cls.result, "table:CitationTable:A1:C3")
        cls.ragged = unit_for(cls.result, "table:RaggedTable:A1:C4")

    def resolve(self, unit, spec: str):
        return resolve_citation(
            unit,
            CitationSelector(region_id=unit.address.container_id, ref_range=spec),
        )

    # -- happy paths -----------------------------------------------------

    def test_a_full_grid_range_resolves_to_every_cell(self) -> None:
        outcome = self.resolve(self.citation, "A1:C3")
        self.assertIsInstance(outcome, RangeCitation)
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(outcome.ref, "A1:C3")
        self.assertEqual(outcome.row_count, 3)
        self.assertEqual(outcome.column_count, 3)
        self.assertEqual(outcome.cell_count, 9)
        self.assertEqual(outcome.lossy_cells, ())

    def test_the_range_grid_matches_the_fixture(self) -> None:
        outcome = self.resolve(self.citation, "A1:C3")
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(
            outcome.values,
            (
                ("Port", "2023", "2024"),
                ("Shanghai", 10.0, 42.0),
                ("Ningbo", 11.0, 42.0),
            ),
        )

    def test_a_data_only_range_resolves(self) -> None:
        outcome = self.resolve(self.citation, "A2:C3")
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(outcome.cell_count, 6)
        self.assertEqual(outcome.range_start, "A2")
        self.assertEqual(outcome.range_end, "C3")

    def test_a_single_cell_range_is_still_a_range_citation(self) -> None:
        outcome = self.resolve(self.citation, "C2")
        self.assertIsInstance(outcome, RangeCitation)
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(outcome.ref, "C2:C2")
        self.assertEqual(outcome.cell_count, 1)
        self.assertNotIsInstance(outcome, Citation)

    def test_reversed_corners_are_normalized_not_rejected(self) -> None:
        """``C3:A2`` names an unambiguous rectangle."""
        forward = self.resolve(self.citation, "A2:C3")
        reversed_ = self.resolve(self.citation, "C3:A2")
        assert isinstance(forward, RangeCitation) and isinstance(reversed_, RangeCitation)
        self.assertEqual(forward.ref, reversed_.ref)
        self.assertEqual(forward.values, reversed_.values)

    def test_absolute_references_are_accepted(self) -> None:
        outcome = self.resolve(self.citation, "$A$2:$C$3")
        self.assertIsInstance(outcome, RangeCitation)
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(outcome.ref, "A2:C3")

    def test_a_range_carries_a_reconstructible_context_path(self) -> None:
        outcome = self.resolve(self.citation, "A2:C3")
        assert isinstance(outcome, RangeCitation)
        for expected in (
            "artifact:art-fixture",
            "source:src-1",
            "sheet:CitationTable",
            "region:table:CitationTable:A1:C3",
            "range:A2:C3",
        ):
            self.assertIn(expected, outcome.context_path)

    # -- holes are reported, never smoothed ---------------------------------

    def test_a_range_with_holes_reports_them(self) -> None:
        """RaggedTable row 2 is short: B2 is blank, C2 has no cell element."""
        outcome = self.resolve(self.ragged, "A1:C3")
        self.assertIsInstance(outcome, RangeCitation)
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(outcome.cell_count, 9)
        self.assertEqual(
            [c.ref for c in outcome.lossy_cells], ["B2", "C2"]
        )
        self.assertTrue(any("not simply present" in n for n in outcome.notes))

    def test_holes_keep_their_distinct_kinds_inside_the_range(self) -> None:
        outcome = self.resolve(self.ragged, "A1:C3")
        assert isinstance(outcome, RangeCitation)
        cells = {c.ref: c for c in outcome.cells}
        self.assertEqual(cells["B2"].value_kind, "empty")
        self.assertEqual(cells["C2"].value_kind, "absent")
        self.assertNotEqual(cells["B2"].value_kind, cells["C2"].value_kind)

    def test_every_coordinate_is_present_exactly_once(self) -> None:
        outcome = self.resolve(self.ragged, "A1:C3")
        assert isinstance(outcome, RangeCitation)
        refs = [c.ref for c in outcome.cells]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual(len(refs), outcome.row_count * outcome.column_count)

    def test_range_loss_aggregates_the_cells_inside_it(self) -> None:
        outcome = self.resolve(self.ragged, "A1:C3")
        assert isinstance(outcome, RangeCitation)
        self.assertIn(TableLossKind.EMPTY, outcome.loss)
        self.assertIn(TableLossKind.ABSENT, outcome.loss)

    # -- refusals ----------------------------------------------------------

    def test_a_range_outside_the_region_is_unresolved(self) -> None:
        outcome = self.resolve(self.citation, "A1:C9")
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, "unresolved")
        self.assertIn("not contained", outcome.message)

    def test_a_range_starting_outside_the_region_is_unresolved(self) -> None:
        outcome = self.resolve(self.citation, "Z1:Z2")
        self.assertIsInstance(outcome, Unresolved)

    def test_a_malformed_range_is_a_malformed_selector(self) -> None:
        outcome = self.resolve(self.citation, "not-a-range")
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, "malformed_selector")

    def test_a_reversed_only_range_with_three_corners_is_rejected(self) -> None:
        outcome = self.resolve(self.citation, "A1:B2:C3")
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, "malformed_selector")

    def test_an_empty_range_string_is_rejected(self) -> None:
        outcome = self.resolve(self.citation, "")
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, "malformed_selector")

    def test_a_range_request_never_returns_a_bare_citation(self) -> None:
        for spec in ("A1:C3", "C2", "A2:C3"):
            with self.subTest(spec=spec):
                outcome = self.resolve(self.citation, spec)
                self.assertNotIsInstance(outcome, Citation)
                self.assertIsInstance(outcome, RangeCitation)

    # -- serialisation -----------------------------------------------------

    def test_range_citation_serialises_completely(self) -> None:
        outcome = self.resolve(self.ragged, "A1:C3")
        assert isinstance(outcome, RangeCitation)
        payload = json.loads(json.dumps(outcome.as_dict(), ensure_ascii=False))
        self.assertEqual(payload["ref"], "A1:C3")
        self.assertEqual(payload["cell_count"], 9)
        self.assertEqual(len(payload["cells"]), 9)
        self.assertEqual(len(payload["values"]), 3)
        self.assertEqual(payload["lossy_cells"], ["B2", "C2"])
        self.assertNotIn("selected", payload)


class RangeInteractionTests(unittest.TestCase):
    """Ranges must not weaken the existing cell-level guarantees."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()

    def test_cell_selection_still_reports_ambiguity(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        outcome = resolve_citation(
            unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", row_header="Shanghai"),
        )
        self.assertIsInstance(outcome, Ambiguous)

    def test_a_range_selector_ignores_the_context_hint_only_when_absent(self) -> None:
        """A range with a mismatched context hint is still refused."""
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        outcome = resolve_citation(
            unit,
            CitationSelector(
                context_hint="sheet:NotThisTable|range:A1:C3", ref_range="A1:C2"
            ),
        )
        self.assertIsInstance(outcome, Unresolved)

    def test_a_range_with_a_matching_context_hint_resolves(self) -> None:
        from skills.luohai.table_context import unit_context_hints

        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        hints = unit_context_hints(unit)
        assert hints is not None
        outcome = resolve_citation(
            unit, CitationSelector(context_hint=hints["A"], ref_range="A2:C3")
        )
        self.assertIsInstance(outcome, RangeCitation)
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(outcome.cell_count, 6)

    def test_an_empty_selector_is_still_rejected(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        outcome = resolve_citation(unit, CitationSelector())
        self.assertIsInstance(outcome, Unresolved)

    def test_range_citation_uniqueness_reflects_the_selector(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        with_identity = resolve_citation(
            unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", ref_range="A1:C2"),
        )
        assert isinstance(with_identity, RangeCitation)
        self.assertEqual(with_identity.uniqueness, "table_context")
        self.assertFalse(with_identity.is_weak)


if __name__ == "__main__":
    unittest.main(verbosity=2)
