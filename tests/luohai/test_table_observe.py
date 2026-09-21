"""V2.1 closure patch -- declared OOXML table observation (Issue 2).

The bounded experiment: when a workbook declares native table objects under
``xl/tables/``, how does that declared metadata compare with the table context
this project *infers* from populated cells?

Three outcomes are asserted separately, because collapsing them would hide the
finding:

* ``agreement``   -- declared and inferred match on range, header row, column
                    count and column names;
* ``disagreement``-- they do not match, reported per aspect so the caller sees
                    exactly what differs;
* ``unavailable`` -- the workbook declares no table for that region, which is
                    the ordinary case and not a loss.

The observation is observation only. Nothing here lets declared metadata
override an inferred boundary.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _bootstrap  # noqa: E402

from core.artifact import Artifact  # noqa: E402
from skills.luohai import ooxml, table_observe  # noqa: E402
from skills.luohai.backends import FixtureXlsxBackend  # noqa: E402
from skills.luohai import TabularEvidenceSkill  # noqa: E402
from fixtures import build_table_context_fixture as builder  # noqa: E402

FIXTURE_PATH = builder.GENERATED_DIR / builder.FIXTURE_NAME

DECLARED_SHEETS = ("DeclaredAgrees", "DeclaredMismatch", "DeclaredTwins")


def package() -> ooxml.RawPackage:
    return ooxml.read_package(str(FIXTURE_PATH))


def build_result():
    artifact = Artifact.from_file(FIXTURE_PATH, "art-context")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return artifact, skill.run(artifact, source_id="src-context")


def declared_by_sheet() -> dict[str, tuple[ooxml.DeclaredTable, ...]]:
    return {sheet.name: sheet.declared_tables for sheet in package().sheets}


def report() -> table_observe.ComparisonReport:
    _, result = build_result()
    return table_observe.compare_declared_and_inferred(
        declared_tables_by_sheet=declared_by_sheet(),
        regions_by_sheet=table_observe.regions_from_result(result),
    )


class DeclaredTableParsingTests(unittest.TestCase):
    """The reader must expose what the workbook declares, verbatim."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.package = package()

    def test_worksheets_without_table_parts_declare_nothing(self) -> None:
        sheet = self.package.sheet_by_name("SingleTable")
        assert sheet is not None
        self.assertEqual(sheet.declared_tables, ())

    def test_declared_table_name_and_range_are_read(self) -> None:
        sheet = self.package.sheet_by_name("DeclaredAgrees")
        assert sheet is not None
        self.assertEqual(len(sheet.declared_tables), 1)
        table = sheet.declared_tables[0]
        self.assertEqual(table.name, "DeclaredAgreesTable")
        self.assertEqual(table.ref, "A1:C3")
        self.assertEqual(table.range_start, "A1")
        self.assertEqual(table.range_end, "C3")

    def test_declared_column_names_are_read(self) -> None:
        sheet = self.package.sheet_by_name("DeclaredAgrees")
        assert sheet is not None
        self.assertEqual(
            sheet.declared_tables[0].column_names, ("Port", "2023", "2024")
        )

    def test_header_row_count_defaults_to_one(self) -> None:
        sheet = self.package.sheet_by_name("DeclaredAgrees")
        assert sheet is not None
        self.assertEqual(sheet.declared_tables[0].header_row_count, 1)
        self.assertEqual(sheet.declared_tables[0].totals_row_count, 0)

    def test_two_declared_tables_are_read_separately(self) -> None:
        sheet = self.package.sheet_by_name("DeclaredTwins")
        assert sheet is not None
        names = [t.name for t in sheet.declared_tables]
        self.assertEqual(names, ["DeclaredTwinFirst", "DeclaredTwinSecond"])
        self.assertEqual(
            [t.ref for t in sheet.declared_tables], ["A1:C3", "A7:C9"]
        )

    def test_a_workbook_without_any_declared_table_is_ordinary(self) -> None:
        sealed = ooxml.read_package(str(_bootstrap.FIXTURE_PATH))
        for sheet in sealed.sheets:
            self.assertEqual(sheet.declared_tables, ())


class DeclaredVersusInferredTests(unittest.TestCase):
    """The comparison itself, on the three declared fixtures."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.report = report()
        cls.by_sheet: dict[str, list] = {}
        for comparison in cls.report.comparisons:
            cls.by_sheet.setdefault(comparison.sheet_name, []).append(comparison)

    def test_the_fixture_declares_four_tables_across_three_sheets(self) -> None:
        self.assertEqual(self.report.declared_table_count, 4)
        self.assertEqual(
            self.report.sheets_with_declared_tables, DECLARED_SHEETS
        )

    def test_all_three_outcomes_are_represented(self) -> None:
        summary = self.report.by_status
        self.assertGreater(summary[table_observe.ObservationStatus.AGREEMENT], 0)
        self.assertGreater(summary[table_observe.ObservationStatus.DISAGREEMENT], 0)
        self.assertGreater(summary[table_observe.ObservationStatus.UNAVAILABLE], 0)

    def test_matching_declaration_is_reported_as_agreement(self) -> None:
        comparisons = self.by_sheet["DeclaredAgrees"]
        self.assertEqual(len(comparisons), 1)
        comparison = comparisons[0]
        self.assertEqual(
            comparison.status, table_observe.ObservationStatus.AGREEMENT
        )
        self.assertEqual(comparison.bounds, "A1:C3")
        self.assertEqual(comparison.declared.name, "DeclaredAgreesTable")
        self.assertEqual(comparison.disagreements, ())

    def test_every_aspect_is_compared_not_just_the_range(self) -> None:
        comparison = self.by_sheet["DeclaredAgrees"][0]
        aspects = {a.aspect for a in comparison.aspects}
        self.assertEqual(
            aspects,
            {
                table_observe.ObservationAspect.RANGE_START,
                table_observe.ObservationAspect.RANGE_END,
                table_observe.ObservationAspect.HEADER_ROW,
                table_observe.ObservationAspect.COLUMN_NAMES,
                table_observe.ObservationAspect.COLUMN_COUNT,
            },
        )

    def test_a_narrower_populated_block_is_a_disagreement_not_an_absence(self) -> None:
        """Declared A1:C5, populated only to C3.

        Matching by "does an inferred region equal the declared range" would
        report "no declared table found", which is false. Matching by containment
        reports the disagreement, which is true.
        """
        comparisons = self.by_sheet["DeclaredMismatch"]
        self.assertEqual(len(comparisons), 1)
        comparison = comparisons[0]
        self.assertEqual(
            comparison.status, table_observe.ObservationStatus.DISAGREEMENT
        )
        self.assertIsNotNone(comparison.declared)
        self.assertEqual(comparison.declared.ref, "A1:C5")
        self.assertEqual(comparison.bounds, "A1:C3")
        differing = {a.aspect: a for a in comparison.disagreements}
        self.assertIn(table_observe.ObservationAspect.RANGE_END, differing)
        self.assertEqual(differing[table_observe.ObservationAspect.RANGE_END].declared, "C5")
        self.assertEqual(differing[table_observe.ObservationAspect.RANGE_END].inferred, "C3")
        # The parts that do match are still reported as matching.
        agreeing = {a.aspect for a in comparison.aspects if a.agrees}
        self.assertIn(table_observe.ObservationAspect.RANGE_START, agreeing)
        self.assertIn(table_observe.ObservationAspect.COLUMN_NAMES, agreeing)

    def test_a_region_with_no_declared_table_is_unavailable(self) -> None:
        comparisons = self.by_sheet["SingleTable"]
        self.assertEqual(len(comparisons), 1)
        comparison = comparisons[0]
        self.assertEqual(
            comparison.status, table_observe.ObservationStatus.UNAVAILABLE
        )
        self.assertIsNone(comparison.declared)
        self.assertIn("no declared OOXML table", comparison.notes[0])

    def test_identical_tables_are_each_matched_to_their_own_declaration(self) -> None:
        """The case inference alone cannot decide.

        Two byte-identical tables in one worksheet produce two indistinguishable
        inferred contexts, but the workbook names them separately. Each inferred
        region must be matched to the declaration that contains it.
        """
        comparisons = {
            c.bounds: c for c in self.by_sheet["DeclaredTwins"]
        }
        self.assertEqual(sorted(comparisons), ["A1:C3", "A7:C9"])
        self.assertEqual(
            comparisons["A1:C3"].declared.name,
            "DeclaredTwinFirst",
        )
        self.assertEqual(
            comparisons["A7:C9"].declared.name,
            "DeclaredTwinSecond",
        )
        for comparison in comparisons.values():
            self.assertEqual(
                comparison.status, table_observe.ObservationStatus.AGREEMENT
            )

    def test_report_serialises_to_json(self) -> None:
        payload = json.loads(json.dumps(self.report.as_dict(), ensure_ascii=False))
        self.assertTrue(payload["provisional"])
        self.assertEqual(payload["declared_table_count"], 4)
        self.assertEqual(len(payload["comparisons"]), len(self.report.comparisons))


class ObservationIsNotAuthorityTests(unittest.TestCase):
    """Declared metadata is observed, never obeyed."""

    def test_declared_metadata_does_not_change_inferred_regions(self) -> None:
        """The inferred region stays A1:C3 even though C5 is declared."""
        _, result = build_result()
        units = {
            unit.address.container_id: unit
            for unit in result.units
            if unit.address.container_id.startswith("table:")
        }
        self.assertIn("table:DeclaredMismatch:A1:C3", units)
        self.assertNotIn("table:DeclaredMismatch:A1:C5", units)

    def test_declared_name_is_not_attached_as_a_table_context_name(self) -> None:
        """The observed name is reported, not promoted into the context."""
        from skills.luohai import table_context

        _, result = build_result()
        unit = next(
            u
            for u in result.units
            if u.address.container_id == "table:DeclaredAgrees:A1:C3"
        )
        context = table_context.unit_table_context(unit)
        assert context is not None
        serialised = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("DeclaredAgreesTable", serialised)
        self.assertFalse(context["boundary"]["declared"])

    def test_observation_declares_itself_partial(self) -> None:
        capability = table_observe.make_capability()
        self.assertEqual(capability.support, "partial")
        self.assertTrue(capability.collapse_risks)

    def test_report_notes_state_the_non_authority(self) -> None:
        notes = " ".join(report().notes)
        self.assertIn("observation only", notes)


class ComparisonUnitTests(unittest.TestCase):
    """Direct tests of the comparison helpers, independent of the fixture."""

    def _declared(self, **overrides) -> ooxml.DeclaredTable:
        payload = {
            "table_id": 1,
            "name": "T",
            "display_name": "T",
            "ref": "A1:C3",
            "column_names": ("Port", "2023", "2024"),
        }
        payload.update(overrides)
        return ooxml.DeclaredTable(**payload)

    def test_agreement_requires_every_aspect(self) -> None:
        outcome = table_observe.compare_observation(
            self._declared(),
            sheet_name="S",
            region_id="r",
            bounds="A1:C3",
            header_row=1,
            header_row_values=["Port", "2023", "2024"],
            column_count=3,
        )
        self.assertEqual(outcome.status, table_observe.ObservationStatus.AGREEMENT)

    def test_a_single_mismatched_column_name_is_a_disagreement(self) -> None:
        outcome = table_observe.compare_observation(
            self._declared(),
            sheet_name="S",
            region_id="r",
            bounds="A1:C3",
            header_row=1,
            header_row_values=["Port", "2023", "TOTAL"],
            column_count=3,
        )
        self.assertEqual(outcome.status, table_observe.ObservationStatus.DISAGREEMENT)
        self.assertEqual(
            [a.aspect for a in outcome.disagreements],
            [table_observe.ObservationAspect.COLUMN_NAMES],
        )

    def test_a_multi_row_header_is_noted(self) -> None:
        outcome = table_observe.compare_observation(
            self._declared(header_row_count=2),
            sheet_name="S",
            region_id="r",
            bounds="A1:C3",
            header_row=1,
            header_row_values=["Port", "2023", "2024"],
            column_count=3,
        )
        self.assertTrue(any("headerRowCount" in n for n in outcome.notes))

    def test_a_declared_totals_row_is_noted(self) -> None:
        outcome = table_observe.compare_observation(
            self._declared(totals_row_count=1, totals_row_shown=True),
            sheet_name="S",
            region_id="r",
            bounds="A1:C3",
            header_row=1,
            header_row_values=["Port", "2023", "2024"],
            column_count=3,
        )
        self.assertTrue(any("totals row" in n for n in outcome.notes))

    def test_no_declared_table_yields_unavailable(self) -> None:
        outcome = table_observe.compare_observation(
            None,
            sheet_name="S",
            region_id="r",
            bounds="A1:C3",
            header_row=1,
            header_row_values=["Port"],
            column_count=1,
        )
        self.assertEqual(outcome.status, table_observe.ObservationStatus.UNAVAILABLE)
        self.assertEqual(outcome.aspects, ())

    def test_containment_matching_finds_a_wider_declaration(self) -> None:
        comparisons = table_observe.observe_declared_tables(
            sheet_name="S",
            declared_tables=(self._declared(ref="A1:C5"),),
            regions=[
                {
                    "region_id": "r",
                    "bounds": "A1:C3",
                    "header_row": 1,
                    "header_row_values": ["Port", "2023", "2024"],
                    "column_count": 3,
                }
            ],
        )
        self.assertEqual(len(comparisons), 1)
        self.assertIsNotNone(comparisons[0].declared)
        self.assertEqual(comparisons[0].declared.ref, "A1:C5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
