"""T5 -- the XLSX adapter, including the C06/C07 calamine spike.

Two paths are exercised behind one interface:

``FixtureXlsxBackend``
    Deterministic, stdlib-only. This is the architecture review's sanctioned
    fallback, and it is the path the citation tests depend on because it
    preserves the empty/absent distinction.

``CalamineBackend``
    Experimental. The spike tests:

    * verify the locked identity of the loaded binding (wheel and extension
      SHA-256) before trusting it;
    * **re-observe** the known loss profile on this fixture rather than
      restating it from the V2.0C note;
    * require the adapter to surface the collapse instead of reporting a
      clean read.

    They are skipped when the binding is not on ``sys.path``. Run
    ``python tests/run_all.py --with-calamine`` to execute them.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _bootstrap  # noqa: E402

from core.artifact import Artifact  # noqa: E402
from core.evidence import LossKind, UnitClass  # noqa: E402
from skills.luohai.backends import CalamineBackend, FixtureXlsxBackend  # noqa: E402
from skills.luohai import TabularEvidenceSkill  # noqa: E402


def fixture_artifact() -> Artifact:
    return Artifact.from_file(_bootstrap.FIXTURE_PATH, "art-fixture")


def run_fixture_backend(options: dict | None = None):
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return skill.run(fixture_artifact(), source_id="src-1", options=options)


def unit_for(result, region_id: str):
    for unit in result.units:
        if unit.address.container_id == region_id:
            return unit
    raise AssertionError(
        f"no unit with container_id {region_id!r}; have "
        f"{[u.address.container_id for u in result.units]}"
    )


class FixtureBackendExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_fixture_backend()

    def test_every_sheet_is_represented(self) -> None:
        represented = self.result.diagnostics.stats["represented_sheets"]
        self.assertEqual(
            represented,
            ["CitationTable", "CnTable", "EmptyCase", "LossTable", "RaggedTable"],
        )

    def test_citation_table_yields_the_expected_region(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        self.assertEqual(unit.unit_class, UnitClass.CONTENT)
        self.assertEqual(unit.payload["tabular"]["bounds"], "A1:C3")
        self.assertEqual(unit.payload["tabular"]["sheet_name"], "CitationTable")
        self.assertEqual(unit.payload["tabular"]["sheet_index"], 1)
        self.assertEqual(unit.content["column_headers"], ["Port", "2023", "2024"])
        self.assertEqual(unit.content["data_row_count"], 2)
        self.assertEqual(unit.content["column_count"], 3)

    def test_units_carry_source_artifact_and_producer(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        self.assertEqual(unit.source_id, "src-1")
        self.assertEqual(unit.artifact_id, "art-fixture")
        self.assertEqual(unit.producer.skill_id, "LuoHai.TabularEvidence")
        self.assertEqual(unit.producer.backend_id, "fixture.ooxml-stdlib")
        self.assertFalse(unit.producer.fallback_used)
        self.assertEqual(unit.provenance, self.result.artifact.content_digest)

    def test_two_blocks_in_one_sheet_are_split_and_reported_as_ambiguous(self) -> None:
        """CitationTable has a one-row block at row 6 under two blank rows.

        At the default ``gap_tolerance=0`` the blocks are separate regions and
        the run says so. This is the honest outcome: the heuristic cannot know
        whether row 6 belongs to the table above, so it neither merges nor
        drops it, and it warns.
        """
        ambiguous = [w for w in self.result.diagnostics.warnings if w.code == "region_ambiguity"]
        self.assertEqual(len(ambiguous), 1)
        self.assertIn("CitationTable", ambiguous[0].message)
        citations = [
            u
            for u in self.result.units
            if (u.payload.get("tabular") or {}).get("sheet_name") == "CitationTable"
        ]
        self.assertEqual(
            sorted(u.payload["tabular"]["bounds"] for u in citations),
            ["A1:C3", "A6:B6"],
        )

    def test_a_large_enough_gap_tolerance_merges_the_blocks(self) -> None:
        """Row 6 is three rows below row 3, so it takes tolerance >= 3 to merge."""
        still_split = run_fixture_backend({"gap_tolerance": 1})
        self.assertTrue(
            [w for w in still_split.diagnostics.warnings if w.code == "region_ambiguity"]
        )

        merged = run_fixture_backend({"gap_tolerance": 3})
        self.assertEqual(
            [w for w in merged.diagnostics.warnings if w.code == "region_ambiguity"], []
        )
        unit = unit_for(merged, "table:CitationTable:A1:C6")
        self.assertEqual(unit.payload["tabular"]["bounds"], "A1:C6")

    def test_per_cell_values_and_kinds_are_preserved(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["C2"]["value"], 42.0)
        self.assertEqual(cells["C2"]["value_kind"], "number")
        self.assertEqual(cells["A2"]["value"], "Shanghai")
        self.assertEqual(cells["A2"]["row_label"], "Shanghai")
        self.assertEqual(cells["C2"]["column_label"], "2024")
        self.assertEqual(cells["C2"]["row_label"], "Shanghai")

    def test_error_value_is_reported_as_an_error(self) -> None:
        unit = unit_for(self.result, "table:LossTable:A1:C2")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["A2"]["value_kind"], "error")
        self.assertEqual(cells["A2"]["value"], "#DIV/0!")

    def test_unresolved_formula_is_marked_unsupported_with_text_kept(self) -> None:
        unit = unit_for(self.result, "table:LossTable:A1:C2")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["C2"]["formula"], "1+2")
        self.assertIsNone(cells["C2"]["value"])
        self.assertIn(LossKind.UNSUPPORTED, cells["C2"]["loss"])
        self.assertIn(LossKind.UNSUPPORTED, unit.loss)

    def test_formula_cache_is_not_an_evaluation(self) -> None:
        unit = unit_for(self.result, "table:LossTable:A1:C2")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["B2"]["formula"], "1+2")
        self.assertEqual(cells["B2"]["value"], 3.0)

    def test_empty_and_absent_are_distinct_including_for_a_whole_sheet(self) -> None:
        unit = unit_for(self.result, "worksheet:EmptyCase")
        self.assertEqual(unit.unit_class, UnitClass.CONTAINER)
        self.assertIn(LossKind.EMPTY, unit.loss)
        self.assertNotIn(LossKind.ABSENT, unit.loss)
        self.assertEqual(unit.content["cell_count"], 0)

    def test_ragged_row_is_flagged_and_its_missing_cell_is_absent(self) -> None:
        unit = unit_for(self.result, "table:RaggedTable:A1:C4")
        self.assertEqual(unit.payload["tabular"]["ragged_rows"], [2])
        self.assertIn(LossKind.ABSENT, unit.loss)
        self.assertIn(LossKind.EMPTY, unit.loss)
        self.assertTrue(any("do not span the full region width" in w for w in unit.self_warnings))
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["B2"]["value_kind"], "empty")
        self.assertEqual(cells["C2"]["value_kind"], "absent")

    def test_a_text_value_is_not_confused_with_the_number_it_resembles(self) -> None:
        unit = unit_for(self.result, "table:RaggedTable:A1:C4")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["B4"]["value"], "42")
        self.assertEqual(cells["B4"]["value_kind"], "string")
        self.assertEqual(cells["C3"]["value"], 42.0)
        self.assertEqual(cells["C3"]["value_kind"], "number")

    def test_cjk_values_survive_extraction(self) -> None:
        unit = unit_for(self.result, "table:CnTable:A1:C3")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["A1"]["value"], "港口")
        self.assertEqual(cells["A2"]["value"], "上海")
        self.assertEqual(cells["C2"]["value"], 270.0)

    def test_no_loss_run_reports_no_complete_success_over_lossy_sheets(self) -> None:
        """The fixture contains known loss, so 'complete success' is False."""
        self.assertTrue(self.result.has_no_fatal_condition)
        self.assertFalse(self.result.is_complete_success)
        self.assertIn(LossKind.EMPTY, self.result.diagnostics.observed_loss_kinds)

    def test_run_is_repeatable(self) -> None:
        first = json.dumps(run_fixture_backend().as_dict(), sort_keys=True)
        second = json.dumps(run_fixture_backend().as_dict(), sort_keys=True)
        # invocation_id and timestamps differ; everything structural must not.
        def strip(payload: str) -> dict:
            data = json.loads(payload)
            data.pop("invocation_id", None)
            data.pop("started_at", None)
            data.pop("finished_at", None)
            data["producer"].pop("run_id", None)
            for unit in data["units"]:
                unit["producer"].pop("run_id", None)
            return data

        self.assertEqual(strip(first), strip(second))


class RegionDetectionTests(unittest.TestCase):
    def test_region_ids_are_unique_within_a_sheet(self) -> None:
        package_units = run_fixture_backend().units
        ids = [u.address.container_id for u in package_units]
        self.assertEqual(len(ids), len(set(ids)), "container ids must be unique")

    def test_sheet_filter_selects_one_sheet(self) -> None:
        result = run_fixture_backend({"sheet_names": ["CnTable"]})
        self.assertEqual(len(result.units), 1)
        self.assertEqual(result.diagnostics.stats["unrepresented_sheets"],
                         ["CitationTable", "EmptyCase", "LossTable", "RaggedTable"])

    def test_worksheet_units_can_be_suppressed(self) -> None:
        result = run_fixture_backend({"emit_worksheet_units": False})
        self.assertFalse(
            any(u.unit_class == UnitClass.CONTAINER for u in result.units)
        )


class UnreadContentTests(unittest.TestCase):
    """Content the backend cannot read must be surfaced, not dropped."""

    def test_declared_unsupported_capabilities_include_unread_content(self) -> None:
        skill = TabularEvidenceSkill(FixtureXlsxBackend())
        names = {c.name for c in skill.capabilities()}
        for expected in (
            "fixture.ooxml-stdlib:cell_comments",
            "fixture.ooxml-stdlib:embedded_objects",
            "fixture.ooxml-stdlib:number_format_display",
            "fixture.ooxml-stdlib:csv_read",
        ):
            self.assertIn(expected, names)

    def test_a_package_with_an_unread_part_raises_a_warning(self) -> None:
        """Synthesise a package carrying a comment part and check it is noticed."""
        import zipfile

        target = _bootstrap.artifacts_dir() / "with_comments.xlsx"
        try:
            with zipfile.ZipFile(_bootstrap.FIXTURE_PATH) as source, zipfile.ZipFile(
                target, "w", zipfile.ZIP_DEFLATED
            ) as sink:
                for item in source.infolist():
                    sink.writestr(item, source.read(item.filename))
                sink.writestr("xl/comments1.xml", "<comments/>")

            backend = FixtureXlsxBackend()
            observation = backend.load(str(target))
            self.assertIn(LossKind.SILENT_LOSS_RISK, observation.loss)
            self.assertTrue(
                any("cell_comments" in w for w in observation.warnings),
                observation.warnings,
            )

            skill = TabularEvidenceSkill(FixtureXlsxBackend())
            artifact = Artifact.from_file(target, "art-comments")
            result = skill.run(artifact, source_id="src-1")
            self.assertTrue(
                any("cell_comments" in w.message for w in result.diagnostics.warnings)
            )
        finally:
            target.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# C06/C07 spike
# --------------------------------------------------------------------------


def calamine_available() -> bool:
    if _bootstrap.calamine_disabled():
        return False
    try:
        _bootstrap.ensure_calamine_on_path()
        import python_calamine  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


@unittest.skipUnless(
    calamine_available(),
    "locked C06/C07 binding not on sys.path (run with --with-calamine)",
)
class CalamineSpikeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = CalamineBackend()
        cls.observation = cls.backend.load(str(_bootstrap.FIXTURE_PATH))
        cls.result = TabularEvidenceSkill(cls.backend).run(
            fixture_artifact(), source_id="src-1"
        )

    # -- locked identity -------------------------------------------------

    def test_locked_identity_is_re_established_before_trusting_the_binding(self) -> None:
        report = self.backend.verify_locked_identity()
        self.assertTrue(report["available"])
        self.assertEqual(
            report["expected_locked_binding_sha"],
            "0a7998e50a7586f308a2d455170ec63c8135dfd3",
        )
        self.assertEqual(
            report["expected_locked_calamine_sha"],
            "0af05f4f6030351e3b8a999ea0810c8618368776",
        )
        # The binding is loaded from the wheel recorded in the AU-03 build
        # provenance, not rebuilt from source here. Claiming otherwise would be
        # exactly the kind of overstatement V2.1 forbids.
        self.assertFalse(report["build_reproduced_here"])

    def test_wheel_and_extension_reverify_against_the_recorded_hashes(self) -> None:
        self.assertTrue(_bootstrap.wheel_is_verified())
        self.assertTrue(_bootstrap.extension_is_verified())

    def test_binding_reports_a_version(self) -> None:
        self.assertTrue(self.backend.backend_version)
        self.assertNotEqual(self.backend.backend_version, "unknown")

    # -- re-observed loss profile ---------------------------------------

    def test_error_value_is_collapsed_to_an_empty_string(self) -> None:
        """Re-observed on this fixture, not restated from the V2.0C note."""
        sheet = self.observation.sheet_by_name("LossTable")
        assert sheet is not None
        cell = sheet.cells["A2"]
        self.assertEqual(cell.value, "")
        # The adapter refuses to call a collapsed "" either empty or absent.
        self.assertEqual(cell.value_kind, "empty_or_collapsed")
        self.assertIn(LossKind.EMPTY, cell.loss)
        self.assertIn(LossKind.ABSENT, cell.loss)

    def test_unresolved_formula_is_collapsed_and_the_text_is_lost(self) -> None:
        sheet = self.observation.sheet_by_name("LossTable")
        assert sheet is not None
        cell = sheet.cells["C2"]
        self.assertEqual(cell.value, "")
        self.assertIsNone(cell.formula)
        self.assertEqual(cell.value_kind, "empty_or_collapsed")

    def test_formula_cache_crosses_the_boundary_but_the_text_does_not(self) -> None:
        sheet = self.observation.sheet_by_name("LossTable")
        assert sheet is not None
        cell = sheet.cells["B2"]
        self.assertEqual(cell.value, 3.0)
        self.assertIsNone(cell.formula)

    def test_empty_sheet_raises_a_base_exception_and_is_contained(self) -> None:
        """The binding panics; the adapter must contain it and say so."""
        sheet = self.observation.sheet_by_name("EmptyCase")
        assert sheet is not None
        self.assertIn(LossKind.FAILED, sheet.loss)
        self.assertTrue(sheet.is_empty)
        self.assertTrue(
            any("EmptyCase" in w for w in self.observation.warnings),
            self.observation.warnings,
        )
        # The run survived and carries the failure as diagnostics.
        self.assertTrue(self.result.has_no_fatal_condition)

    def test_hidden_state_comments_and_merges_are_declared_lost(self) -> None:
        sheet = self.observation.sheet_by_name("CnTable")
        assert sheet is not None
        self.assertIn(LossKind.SILENT_LOSS_RISK, sheet.loss)
        self.assertTrue(
            any("hidden state" in note for note in sheet.notes), sheet.notes
        )

    def test_integers_are_widened_to_float(self) -> None:
        sheet = self.observation.sheet_by_name("CitationTable")
        assert sheet is not None
        self.assertEqual(sheet.cells["C2"].value, 42.0)
        self.assertIsInstance(sheet.cells["C2"].value, float)

    # -- the fixture backend as the reference ---------------------------

    def test_both_backends_agree_on_the_clean_cells(self) -> None:
        """The two readers must agree wherever the arithmetic is unambiguous.

        Note the deliberate asymmetry: the calamine binding pads a sheet to a
        dense matrix, so its region for ``CitationTable`` spans ``A1:C6``
        whereas the fixture backend splits the trailing block off at the
        default gap tolerance. The comparison is therefore restricted to the
        coordinates both readers populated with a concrete value -- the cells
        the citation query actually turns on.
        """
        reference = run_fixture_backend({"gap_tolerance": 3})
        reference_unit = unit_for(reference, "table:CitationTable:A1:C6")
        spike_unit = unit_for(self.result, "table:CitationTable:A1:C6")

        def concrete_values(unit):
            return {
                c["ref"]: c["value"]
                for c in unit.payload["tabular"]["cells"]
                if c["value_kind"]
                in ("number", "string", "inline_string", "boolean", "error")
            }

        reference_values = concrete_values(reference_unit)
        spike_values = concrete_values(spike_unit)

        for ref in ("A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3", "C3"):
            self.assertIn(ref, reference_values)
            self.assertIn(ref, spike_values)
            self.assertEqual(
                reference_values[ref], spike_values[ref], f"readers disagree at {ref}"
            )
        self.assertEqual(reference_values["C2"], 42.0)

    def test_both_backends_agree_on_the_column_headers(self) -> None:
        reference = unit_for(run_fixture_backend(), "table:CnTable:A1:C3")
        spike = unit_for(self.result, "table:CnTable:A1:C3")
        self.assertEqual(
            reference.content["column_headers"], spike.content["column_headers"]
        )
        self.assertEqual(reference.content["bounds"], spike.content["bounds"])

    def test_cjk_is_preserved_by_the_binding(self) -> None:
        sheet = self.observation.sheet_by_name("CnTable")
        assert sheet is not None
        self.assertEqual(sheet.cells["A1"].value, "港口")
        self.assertEqual(sheet.cells["A2"].value, "上海")

    # -- fail-closed behaviour on the spike -----------------------------

    def test_spike_run_is_not_a_complete_success(self) -> None:
        self.assertFalse(self.result.is_complete_success)

    def test_declared_collapse_risks_are_all_surfaced(self) -> None:
        self.assertEqual(self.result.unsurfaced_risks, ())
        self.assertTrue(self.result.diagnostics.known_collapse_risks)
        self.assertTrue(self.result.diagnostics.observed_loss_kinds)

    def test_spike_units_are_attributed_to_the_binding(self) -> None:
        for unit in self.result.units:
            self.assertEqual(unit.producer.backend_id, "calamine.python-calamine")

    def test_spike_does_not_claim_the_lossy_distinctions(self) -> None:
        capabilities = {c.name: c for c in self.backend.capabilities()}
        for name in (
            "error_state",
            "empty_vs_absent",
            "formula_text",
            "hidden_sheet_state",
            "merged_cell_state",
        ):
            self.assertNotEqual(
                capabilities[name].support,
                "supported",
                f"the spike must not claim {name} is supported",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
