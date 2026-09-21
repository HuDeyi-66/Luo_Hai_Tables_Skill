"""V2.2 -- ``LuoHai.TabularEvidence`` contract tests.

One test per capability the V2.2 task names as required, plus the prohibitions.
The point of this file is that each required capability has a *named* test, so
"it is implemented" is a claim a reviewer can check by reading the test list
rather than by trusting a summary.

Required capabilities:
    source/artifact reference, XLSX extraction, table context, cell/range
    location, loss diagnostics, unsupported states, citation reconstruction.

Prohibitions:
    silent success, first match, registry / auto-discovery / plugin marketplace,
    RAG / retrieval / ranking / vector / embeddings / LLM / agent / workflow /
    database / schema freeze.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import _bootstrap  # noqa: E402

from core.artifact import Artifact  # noqa: E402
from core.evidence import CitationAddress, EvidenceUnit, LossKind, UnitClass  # noqa: E402
from core.skill_result import Skill, SkillResult, Support  # noqa: E402
from core.source import SourceRegistry  # noqa: E402
from skills.luohai import (  # noqa: E402
    Ambiguous,
    Citation,
    CitationSelector,
    FakeTabularBackend,
    FixtureXlsxBackend,
    TableResolution,
    TabularEvidenceSkill,
    Unresolved,
    resolve_citation,
    resolve_table_context,
    unit_table_context,
)
from skills.luohai.citation import RangeCitation  # noqa: E402
from skills.luohai.table_context import (  # noqa: E402
    unit_context_hints,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FIXTURE = _bootstrap.FIXTURE_PATH

#: The V2.1 fixture above is deliberately small: six regions, all with distinct
#: addresses. Address collisions are exercised by the larger table-context
#: fixture, where five separate worksheets happen to share the region ``A1:C3``.
from fixtures import build_table_context_fixture as _context_fixture  # noqa: E402

CONTEXT_FIXTURE = (
    _context_fixture.GENERATED_DIR / _context_fixture.FIXTURE_NAME
)


def build(options: dict | None = None):
    artifact = Artifact.from_file(FIXTURE, "art-fixture")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return artifact, skill.run(artifact, source_id="src-1", options=options or {})


def build_context_fixture():
    artifact = Artifact.from_file(CONTEXT_FIXTURE, "art-context")
    skill = TabularEvidenceSkill(FixtureXlsxBackend())
    return artifact, skill.run(artifact, source_id="src-context")


def unit_for(result, container_id: str) -> EvidenceUnit:
    return next(u for u in result.units if u.address.container_id == container_id)


class Capability_1_SourceArtifactReferenceTests(unittest.TestCase):
    """Required: Source/Artifact reference on every unit."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()

    def test_every_unit_references_a_source_and_an_artifact(self) -> None:
        self.assertTrue(self.result.units)
        for unit in self.result.units:
            self.assertEqual(unit.source_id, "src-1")
            self.assertEqual(unit.artifact_id, "art-fixture")

    def test_unit_provenance_carries_the_content_digest(self) -> None:
        for unit in self.result.units:
            self.assertEqual(unit.provenance, self.artifact.content_digest)

    def test_a_unit_is_traceable_back_through_a_registry(self) -> None:
        registry = SourceRegistry()
        registry.register_source("src-1", label="LuoHai fixture")
        artifact = registry.register_artifact("src-1", FIXTURE)
        skill = TabularEvidenceSkill(FixtureXlsxBackend())
        result = skill.run(artifact, source_id="src-1")

        for unit in result.units:
            source = registry.source_of(unit.artifact_id)
            self.assertEqual(source.source_id, unit.source_id)
            self.assertEqual(
                registry.get_artifact(unit.artifact_id).digest, artifact.digest
            )

    def test_missing_source_identity_fails_closed(self) -> None:
        artifact = Artifact.from_file(FIXTURE, "art-fixture")
        result = TabularEvidenceSkill(FixtureXlsxBackend()).run(artifact)
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertFalse(result.is_complete_success)


class Capability_2_XlsxExtractionTests(unittest.TestCase):
    """Required: XLSX extraction."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()

    def test_the_skill_is_a_core_skill(self) -> None:
        self.assertIsInstance(TabularEvidenceSkill(FixtureXlsxBackend()), Skill)

    def test_skill_identity_and_version_are_reported(self) -> None:
        self.assertEqual(self.result.skill_id, "LuoHai.TabularEvidence")
        self.assertEqual(self.result.producer.skill_id, "LuoHai.TabularEvidence")
        self.assertTrue(self.result.producer.skill_version)
        self.assertEqual(self.result.producer.method, "read_only_extract")

    def test_every_fixture_sheet_is_extracted(self) -> None:
        self.assertEqual(
            self.result.diagnostics.stats["represented_sheets"],
            ["CitationTable", "CnTable", "EmptyCase", "LossTable", "RaggedTable"],
        )

    def test_extraction_produces_typed_units(self) -> None:
        classes = {unit.unit_class for unit in self.result.units}
        self.assertIn(UnitClass.CONTENT, classes)
        self.assertIn(UnitClass.CONTAINER, classes)

    def test_callers_own_the_artifact_and_it_is_not_mutated(self) -> None:
        before = FIXTURE.read_bytes()
        build()
        self.assertEqual(FIXTURE.read_bytes(), before)


class Capability_3_TableContextTests(unittest.TestCase):
    """Required: table context."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()

    def test_every_tabular_unit_carries_context(self) -> None:
        for unit in self.result.units:
            if unit.unit_class != UnitClass.CONTENT:
                continue
            self.assertIsNotNone(unit_table_context(unit))

    def test_context_exposes_the_recommended_shape(self) -> None:
        context = unit_table_context(unit_for(self.result, "table:CitationTable:A1:C3"))
        assert context is not None
        for key in ("container", "boundary", "context_hints"):
            self.assertIn(key, context)

    def test_context_is_experimental_and_unfrozen(self) -> None:
        context = unit_table_context(unit_for(self.result, "table:CitationTable:A1:C3"))
        assert context is not None
        self.assertTrue(context["experimental"])
        self.assertTrue(context["unfrozen"])

    def test_three_candidate_hints_are_produced(self) -> None:
        hints = unit_context_hints(unit_for(self.result, "table:CitationTable:A1:C3"))
        assert hints is not None
        self.assertEqual(sorted(hints), ["A", "B", "C"])

    def test_table_context_resolution_reports_ambiguity_without_choosing(self) -> None:
        """In the context fixture, several worksheets share the region ``A1:C3``.

        A caller supplying only that address has not said which table they mean,
        so the resolver must refuse and list all of them. Picking one would be
        exactly the silent selection the project forbids.
        """
        from skills.luohai import build_table_context
        from skills.luohai.table_context import (
            TableContextQuery,
            resolve_table_query,
        )

        _, context_result = build_context_fixture()
        contexts = {}
        counters: dict[str, int] = {}
        for unit in context_result.units:
            block = (unit.payload or {}).get("tabular")
            if not isinstance(block, dict):
                continue
            sheet = str(block.get("sheet_name"))
            counters[sheet] = counters.get(sheet, 0) + 1
            contexts[f"{sheet}#{counters[sheet]}"] = build_table_context(block)

        colliding = [
            name
            for name, context in contexts.items()
            if context.bounds == "A1:C3"
        ]
        self.assertGreater(len(colliding), 1)

        outcome = resolve_table_query(
            contexts, TableContextQuery(candidate="A", scope="artifact", bounds="A1:C3")
        )
        self.assertFalse(outcome.unique)
        self.assertEqual(len(outcome.candidates), len(colliding))

    def test_the_v2_1_fixture_has_no_address_collisions(self) -> None:
        """Why the two fixtures are kept separate.

        Every region of the small V2.1 fixture has a distinct *container id*
        (worksheet + bounds), which is what makes it a usable regression
        baseline. Bare bounds are deliberately allowed to repeat -- two
        worksheets may both start at ``A1`` -- so collisions of that weaker kind
        are added explicitly in the context fixture rather than appearing by
        accident in the baseline.
        """
        container_ids = [
            unit.address.container_id
            for unit in self.result.units
            if unit.address.container_id.startswith("table:")
        ]
        self.assertEqual(len(container_ids), len(set(container_ids)))

    def test_a_fully_qualified_context_is_unique(self) -> None:
        units = tuple(self.result.units)
        unit = unit_for(self.result, "table:RaggedTable:A1:C4")
        hints = unit_context_hints(unit)
        assert hints is not None
        outcome = resolve_table_context(units, hint=hints["A"], candidate="A")
        self.assertIsInstance(outcome, TableResolution)
        self.assertTrue(outcome.unique)
        assert outcome.table is not None
        self.assertEqual(outcome.table.region_id, "table:RaggedTable:A1:C4")


class Capability_4_CellAndRangeLocationTests(unittest.TestCase):
    """Required: cell/range location."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()
        cls.unit = unit_for(cls.result, "table:CitationTable:A1:C3")

    def test_cell_location_by_explicit_coordinate(self) -> None:
        outcome = resolve_citation(
            self.unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", ref="C2"),
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual((outcome.ref, outcome.value), ("C2", 42.0))

    def test_cell_location_by_row_and_column_header(self) -> None:
        outcome = resolve_citation(
            self.unit,
            CitationSelector(
                region_id="table:CitationTable:A1:C3",
                row_header="Shanghai",
                column_header="2024",
            ),
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.ref, "C2")

    def test_cell_location_by_row_and_column_index(self) -> None:
        outcome = resolve_citation(
            self.unit,
            CitationSelector(
                region_id="table:CitationTable:A1:C3", row_index=2, column_index=3
            ),
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.ref, "C2")

    def test_cell_location_by_value(self) -> None:
        outcome = resolve_citation(
            self.unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", value=10.0),
        )
        self.assertIsInstance(outcome, Citation)
        assert isinstance(outcome, Citation)
        self.assertEqual(outcome.ref, "B2")

    def test_range_location_returns_a_range_citation(self) -> None:
        outcome = resolve_citation(
            self.unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", ref_range="A1:C2"),
        )
        self.assertIsInstance(outcome, RangeCitation)
        assert isinstance(outcome, RangeCitation)
        self.assertEqual(outcome.ref, "A1:C2")
        self.assertEqual(outcome.cell_count, 6)
        self.assertEqual(len(outcome.values), 2)
        self.assertEqual(len(outcome.values[0]), 3)

    def test_a_citation_carries_a_reconstructible_context_path(self) -> None:
        outcome = resolve_citation(
            self.unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", ref="C2"),
        )
        assert isinstance(outcome, Citation)
        for expected in (
            "artifact:art-fixture",
            "source:src-1",
            "sheet:CitationTable",
            "region:table:CitationTable:A1:C3",
            "cell:C2",
        ):
            self.assertIn(expected, outcome.context_path)

    def test_locations_survive_a_round_trip_to_the_package(self) -> None:
        from skills.luohai import ooxml

        package = ooxml.read_package(str(FIXTURE))
        outcome = resolve_citation(
            self.unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", ref="C2"),
        )
        assert isinstance(outcome, Citation)
        sheet = package.sheet_by_name(outcome.sheet_name)
        assert sheet is not None
        self.assertEqual(sheet.cells[outcome.ref].value, outcome.value)


class Capability_5_LossDiagnosticsTests(unittest.TestCase):
    """Required: loss diagnostics and unsupported states."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()

    def test_distinct_loss_kinds_are_surfaced_on_the_fixture(self) -> None:
        observed = set(self.result.diagnostics.observed_loss_kinds)
        self.assertTrue(
            {LossKind.EMPTY, LossKind.ABSENT, LossKind.UNSUPPORTED}.issubset(observed),
            observed,
        )

    def test_the_fixture_run_is_not_reported_as_complete_success(self) -> None:
        self.assertTrue(self.result.has_no_fatal_condition)
        self.assertFalse(self.result.is_complete_success)

    def test_empty_and_absent_are_reported_on_different_kinds(self) -> None:
        unit = unit_for(self.result, "table:RaggedTable:A1:C4")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["B2"]["value_kind"], "empty")
        self.assertEqual(cells["C2"]["value_kind"], "absent")
        self.assertNotEqual(cells["B2"]["value_kind"], cells["C2"]["value_kind"])

    def test_unsupported_states_are_declared_not_hidden(self) -> None:
        names = self.result.diagnostics.unsupported_capabilities
        self.assertTrue(names)
        self.assertTrue(any("csv_read" in n for n in names))

    def test_loss_kinds_reach_the_unit_that_owns_them(self) -> None:
        unit = unit_for(self.result, "table:LossTable:A1:C2")
        self.assertIn(LossKind.UNSUPPORTED, unit.loss)
        self.assertIn(LossKind.EMPTY, unit.loss)

    def test_an_error_value_is_not_flattened_into_blank(self) -> None:
        unit = unit_for(self.result, "table:LossTable:A1:C2")
        cells = {c["ref"]: c for c in unit.payload["tabular"]["cells"]}
        self.assertEqual(cells["A2"]["value_kind"], "error")
        self.assertEqual(cells["A2"]["value"], "#DIV/0!")

    def test_capability_statement_distinguishes_supported_from_unsupported(self) -> None:
        skill = TabularEvidenceSkill(FixtureXlsxBackend())
        capabilities = {c.name: c for c in skill.capabilities()}
        supported = [
            c for c in capabilities.values() if c.support == Support.SUPPORTED
        ]
        unsupported = [
            c for c in capabilities.values() if c.support == Support.UNSUPPORTED
        ]
        self.assertTrue(supported)
        self.assertTrue(unsupported)


class Capability_6_CitationReconstructionTests(unittest.TestCase):
    """Required: citation reconstruction, and the ban on first match."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()

    def test_multiple_matches_return_ambiguous_not_a_choice(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        outcome = resolve_citation(
            unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", row_header="Shanghai"),
        )
        self.assertIsInstance(outcome, Ambiguous)
        assert isinstance(outcome, Ambiguous)
        self.assertEqual(sorted(outcome.candidate_refs), ["A2", "B2", "C2"])

    def test_ambiguous_output_lists_every_candidate(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        outcome = resolve_citation(
            unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", row_header="Shanghai"),
        )
        payload = json.loads(json.dumps(outcome.as_dict()))
        self.assertEqual(payload["status"], "ambiguous")
        self.assertEqual(len(payload["candidates"]), 3)
        self.assertNotIn("selected", payload)

    def test_no_match_is_unresolved_and_distinct_from_ambiguous(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        outcome = resolve_citation(
            unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", ref="ZZ99"),
        )
        self.assertIsInstance(outcome, Unresolved)
        assert isinstance(outcome, Unresolved)
        self.assertEqual(outcome.problem, "unresolved")

    def test_naming_a_table_never_returns_an_unrequested_cell(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        hint = unit_context_hints(unit)["A"]
        outcome = resolve_table_context(
            list(self.result.units), hint=hint, candidate="A"
        )
        self.assertNotIsInstance(outcome, (Citation, RangeCitation))
        self.assertIsInstance(outcome, TableResolution)

    def test_a_range_request_never_degrades_to_a_single_cell(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        outcome = resolve_citation(
            unit,
            CitationSelector(region_id="table:CitationTable:A1:C3", ref_range="A1:C3"),
        )
        self.assertNotIsInstance(outcome, Citation)
        self.assertIsInstance(outcome, RangeCitation)


class ProhibitionTests(unittest.TestCase):
    """The explicit 'do not implement' list, checked against the code itself."""

    FORBIDDEN_MODULES = (
        "sqlite3",
        "sqlalchemy",
        "numpy",
        "pandas",
        "requests",
        "openai",
        "langchain",
        "chromadb",
        "faiss",
        "transformers",
    )
    FORBIDDEN_NAMES = (
        "registry",
        "plugin_marketplace",
        "auto_discover",
        "embedding",
        "vectorstore",
        "vector_store",
        "retriever",
        "ranker",
        "workflow_engine",
    )

    def _project_sources(self):
        for path in sorted((PROJECT_ROOT / "skills").rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            yield path

    def test_no_forbidden_dependency_is_imported(self) -> None:
        offenders: list[str] = []
        for path in self._project_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in self.FORBIDDEN_MODULES:
                        offenders.append(f"{path.name}: {name}")
        self.assertEqual(offenders, [], f"forbidden dependencies imported: {offenders}")

    def test_no_registry_or_discovery_machinery_exists(self) -> None:
        offenders: list[str] = []
        for path in self._project_sources():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            defined = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef))
            }
            for name in defined:
                lowered = name.lower()
                for forbidden in self.FORBIDDEN_NAMES:
                    if forbidden in lowered:
                        offenders.append(f"{path.name}: {name}")
        self.assertEqual(offenders, [], f"forbidden machinery defined: {offenders}")

    def test_backend_wiring_is_explicit_and_bounded(self) -> None:
        """Backends are injected; there is no scanning or dynamic import loop."""
        skill = TabularEvidenceSkill(FixtureXlsxBackend())
        candidates = skill._candidate_backends({})  # noqa: SLF001 - order is the contract
        self.assertEqual(
            [b.backend_id for b in candidates], ["fixture.ooxml-stdlib"]
        )
        self.assertEqual(
            [
                b.backend_id
                for b in TabularEvidenceSkill()._candidate_backends({})  # noqa: SLF001
            ],
            ["fixture.ooxml-stdlib"],
        )

    def test_core_address_and_unit_classes_are_modality_neutral(self) -> None:
        address_fields = set(CitationAddress.__dataclass_fields__)  # type: ignore[attr-defined]
        self.assertTrue(
            {
                "sheet_id",
                "sheet_index",
                "bounds",
                "row_index",
                "column_index",
                "row_header",
                "column_header",
            }.isdisjoint(address_fields)
        )
        self.assertEqual(
            set(UnitClass.ALL),
            {UnitClass.CONTENT, UnitClass.CONTAINER, UnitClass.UNCLASSIFIED},
        )

    def test_live_table_api_uses_context_not_identity_names(self) -> None:
        offenders: list[str] = []
        for path in sorted((PROJECT_ROOT / "skills" / "luohai").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for forbidden in (
                "compare_identities",
                "sheet_identity",
                "table_identity",
            ):
                if forbidden in source:
                    offenders.append(f"{path.name}: {forbidden}")
        self.assertEqual(offenders, [])

    def test_a_fake_backend_can_drive_the_interface_without_xlsx(self) -> None:
        sheet = FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))
        skill = TabularEvidenceSkill(FakeTabularBackend([sheet]))
        artifact = Artifact.from_file(FIXTURE, "art-fixture")
        result = skill.run(artifact, source_id="src-1")
        self.assertEqual(result.diagnostics.backend_id, "fake.tabular")
        self.assertTrue(result.units)


class ResultShapeTests(unittest.TestCase):
    """The declared output shape: SkillResult -> EvidenceUnit[]."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.result = build()

    def test_output_is_a_skill_result_over_evidence_units(self) -> None:
        self.assertIsInstance(self.result, SkillResult)
        self.assertTrue(all(isinstance(u, EvidenceUnit) for u in self.result.units))

    def test_result_is_json_serialisable_end_to_end(self) -> None:
        payload = json.loads(json.dumps(self.result.as_dict(), ensure_ascii=False))
        self.assertEqual(payload["skill_id"], "LuoHai.TabularEvidence")
        self.assertEqual(len(payload["units"]), len(self.result.units))
        self.assertIn("diagnostics", payload)
        self.assertIn("assessment", payload)

    def test_unit_payload_rebuilds_through_serialisation(self) -> None:
        unit = unit_for(self.result, "table:CitationTable:A1:C3")
        restored = EvidenceUnit.from_dict(json.loads(json.dumps(unit.as_dict())))
        self.assertEqual(restored.unit_id, unit.unit_id)
        self.assertEqual(restored.address.as_dict(), unit.address.as_dict())
        self.assertEqual(
            unit_table_context(restored), unit_table_context(unit)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
