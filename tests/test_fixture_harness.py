"""T1 -- the fixture and its repeat-and-diff harness.

These tests exist before any extraction code, per the V2.1 development order.
They pin two properties:

* the fixture rebuilds byte-identically, so a "silent loss" result cannot be
  blamed on fixture drift;
* the fixture is a real XLSX -- an independent reader (``openpyxl``, installed
  outside this project) must see the same cells the hand-written XML declares.
  The ``openpyxl`` check is skipped when the library is absent so the suite
  stays stdlib-only by default.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: E402

from fixtures import build_fixture  # noqa: E402
from skills.luohai import ooxml  # noqa: E402


class FixtureDeterminismTests(unittest.TestCase):
    def test_rebuild_is_byte_identical(self) -> None:
        first = build_fixture.build_workbook_bytes()
        second = build_fixture.build_workbook_bytes()
        self.assertEqual(
            build_fixture._sha256(first),
            build_fixture._sha256(second),
            "fixture rebuild is not byte-identical",
        )

    def test_written_fixture_matches_manifest(self) -> None:
        manifest = json.loads(_bootstrap.MANIFEST_PATH.read_text(encoding="utf-8"))
        payload = _bootstrap.FIXTURE_PATH.read_bytes()
        self.assertEqual(build_fixture._sha256(payload), manifest["sha256"])
        self.assertEqual(len(payload), manifest["bytes"])

    def test_rebuild_matches_committed_fixture(self) -> None:
        """A rebuild must not silently change the pinned fixture."""
        rebuilt = build_fixture.build_workbook_bytes()
        self.assertEqual(
            rebuilt,
            _bootstrap.FIXTURE_PATH.read_bytes(),
            "fixtures/build_fixture.py output drifted from the committed fixture; "
            "regenerate the fixture and its truth manifest together",
        )

    def test_truth_manifest_is_pinned_to_the_fixture(self) -> None:
        truth = json.loads(_bootstrap.TRUTH_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            truth["fixture_sha256"], build_fixture._sha256(_bootstrap.FIXTURE_PATH.read_bytes())
        )


class FixtureStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = ooxml.read_package(str(_bootstrap.FIXTURE_PATH))

    def test_expected_sheets_in_order(self) -> None:
        self.assertEqual(
            [s.name for s in self.package.sheets],
            ["CitationTable", "LossTable", "CnTable", "RaggedTable", "EmptyCase"],
        )

    def test_repeated_labels_are_present(self) -> None:
        sheet = self.package.sheet_by_name("CitationTable")
        assert sheet is not None
        labels = [
            sheet.cells[f"A{r}"].value for r in range(1, 7) if f"A{r}" in sheet.cells
        ]
        self.assertEqual(labels.count("Shanghai"), 1)
        self.assertEqual(labels.count("Ningbo"), 2)

    def test_value_42_recurs_so_a_bare_value_cannot_locate(self) -> None:
        """Three cells hold 42 across two sheets: identity is not the value."""
        occurrences = []
        for sheet in self.package.sheets:
            for cell in sheet.cells.values():
                value = cell.value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if float(value) == 42.0:
                        occurrences.append(f"{sheet.name}!{cell.ref}")
        self.assertEqual(
            sorted(occurrences),
            ["CitationTable!C2", "CitationTable!C3", "RaggedTable!C3"],
        )

    def test_error_cell_is_an_error_not_a_blank(self) -> None:
        sheet = self.package.sheet_by_name("LossTable")
        assert sheet is not None
        cell = sheet.cells["A2"]
        self.assertEqual(cell.kind, "error")
        self.assertEqual(cell.value, "#DIV/0!")

    def test_formula_with_cached_value_keeps_both_facts(self) -> None:
        """LossTable!B2 carries '<f>1+2</f><v>3</v>': text and cache, separately."""
        sheet = self.package.sheet_by_name("LossTable")
        assert sheet is not None
        formula_cell = sheet.cells["B2"]
        self.assertEqual(formula_cell.formula, "1+2")
        self.assertEqual(formula_cell.value, 3.0)

    def test_unresolved_formula_has_text_and_no_cached_value(self) -> None:
        """LossTable!C2 is '<f>1+2</f>' with no <v> at all."""
        sheet = self.package.sheet_by_name("LossTable")
        assert sheet is not None
        cell = sheet.cells["C2"]
        self.assertEqual(cell.formula, "1+2")
        self.assertIsNone(cell.value)
        self.assertTrue(cell.structurally_blank)

    def test_present_but_blank_cell(self) -> None:
        sheet = self.package.sheet_by_name("RaggedTable")
        assert sheet is not None
        cell = sheet.cells["B2"]
        self.assertTrue(cell.element_present)
        self.assertEqual(cell.kind, "blank")
        self.assertTrue(cell.structurally_blank)

    def test_absent_coordinate_has_no_element(self) -> None:
        sheet = self.package.sheet_by_name("RaggedTable")
        assert sheet is not None
        self.assertNotIn("C2", sheet.cells)

    def test_empty_sheet_has_no_cells(self) -> None:
        sheet = self.package.sheet_by_name("EmptyCase")
        assert sheet is not None
        self.assertEqual(sheet.cells, {})

    def test_cjk_shared_strings_survive(self) -> None:
        sheet = self.package.sheet_by_name("CnTable")
        assert sheet is not None
        self.assertEqual(sheet.cells["A1"].value, "港口")
        self.assertEqual(sheet.cells["A2"].value, "上海")


class IndependentReaderTests(unittest.TestCase):
    """Cross-check the hand-written fixture against a third-party reader."""

    def test_openpyxl_sees_the_same_cells(self) -> None:
        try:
            import openpyxl  # type: ignore
        except ImportError:  # pragma: no cover - environment dependent
            self.skipTest("openpyxl is not installed; setuptools-free cross-check skipped")

        workbook = openpyxl.load_workbook(str(_bootstrap.FIXTURE_PATH), data_only=False)
        self.assertEqual(
            workbook.sheetnames,
            ["CitationTable", "LossTable", "CnTable", "RaggedTable", "EmptyCase"],
        )
        sheet = workbook["CitationTable"]
        self.assertEqual(sheet["A1"].value, "Port")
        self.assertEqual(sheet["C2"].value, 42)
        self.assertEqual(sheet["A6"].value, "Ningbo")
        # openpyxl reports absent coordinates as None, matching the package.
        self.assertIsNone(sheet["C6"].value)
        self.assertIsNone(sheet["A4"].value)

        loss = workbook["LossTable"]
        self.assertEqual(loss["A2"].value, "#DIV/0!")
        self.assertEqual(loss["A2"].data_type, "e")
        self.assertEqual(loss["B2"].value, "=1+2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
