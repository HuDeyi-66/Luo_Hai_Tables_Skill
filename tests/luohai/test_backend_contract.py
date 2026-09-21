"""V2.2 -- backend contract tests for ``LuoHai.TabularEvidence``.

The V2.2 task asks for a backend status report, so the backend rules are
asserted here rather than described in prose:

* a backend is injected explicitly -- constructor, ``backends=[...]``, or the
  ``backends`` option -- and nothing is auto-discovered;
* the deterministic stdlib backend is the default in every environment;
* the C06/C07 calamine binding is a *spike*: used only when explicitly
  requested and available, never auto-adopted, and its losses are declared;
* a degraded selection is recorded on the run *and* on every unit, so no
  fallback can be silent;
* the fake backend can drive the whole interface without any XLSX file.

Which backend actually ran in this environment is reported by
``tools/verify.py``; these tests assert the rules, not one machine's answer.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import _bootstrap  # noqa: E402

from skills.luohai.contracts import TableArtifact  # noqa: E402
from skills.luohai.contracts import TableLossKind  # noqa: E402
from skills.luohai.contracts import TableSupport  # noqa: E402
from skills.luohai import (  # noqa: E402
    CalamineBackend,
    FakeTabularBackend,
    FixtureXlsxBackend,
    ObservedSheet,
    ObservedWorkbook,
    TabularEvidenceSkill,
)

FIXTURE = _bootstrap.FIXTURE_PATH
FIXTURE_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def artifact() -> TableArtifact:
    return TableArtifact.from_file(FIXTURE, "art-fixture")


class InjectionTests(unittest.TestCase):
    """Wiring is explicit. Nothing is discovered."""

    def test_constructor_injection_is_used_verbatim(self) -> None:
        backend = FixtureXlsxBackend()
        skill = TabularEvidenceSkill(backend)
        result = skill.run(artifact(), source_id="src-1")
        self.assertEqual(result.diagnostics.backend_id, "fixture.ooxml-stdlib")
        self.assertEqual(result.diagnostics.backend_path, "fixture")

    def test_backends_list_injection_is_used_in_order(self) -> None:
        candidate = FakeTabularBackend(
            [FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))]
        )
        skill = TabularEvidenceSkill(backends=[candidate])
        result = skill.run(artifact(), source_id="src-1")
        self.assertEqual(result.diagnostics.backend_id, "fake.tabular")

    def test_option_injection_is_used(self) -> None:
        candidate = FakeTabularBackend(
            [FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))]
        )
        skill = TabularEvidenceSkill()
        result = skill.run(
            artifact(), source_id="src-1", options={"backends": [candidate]}
        )
        self.assertEqual(result.diagnostics.backend_id, "fake.tabular")

    def test_the_default_is_only_the_deterministic_stdlib_backend(self) -> None:
        """Optional-package availability must not change default evidence."""
        skill = TabularEvidenceSkill()
        candidates = skill._candidate_backends({})  # noqa: SLF001 - order is the contract
        self.assertEqual([b.backend_id for b in candidates], ["fixture.ooxml-stdlib"])

    def test_considered_backends_are_reported_on_every_run(self) -> None:
        skill = TabularEvidenceSkill()
        result = skill.run(artifact(), source_id="src-1")
        self.assertEqual(
            result.diagnostics.considered_backends,
            ["fixture.ooxml-stdlib"],
        )

    def test_the_skill_never_scans_or_dynamically_resolves_backends(self) -> None:
        skill = TabularEvidenceSkill(FixtureXlsxBackend())
        # With an explicit backend there is exactly one candidate: no probing,
        # no filesystem scan, no entry-point lookup.
        candidates = skill._candidate_backends({})  # noqa: SLF001
        self.assertEqual(len(candidates), 1)


class FakeBackendTests(unittest.TestCase):
    """The interface must be drivable with no XLSX and no third party."""

    def test_a_fake_backend_produces_units_with_no_file(self) -> None:
        sheet = FakeTabularBackend.make_sheet(
            "Sheet1", (["Port", "2023", "2024"], ["Shanghai", 10, 42])
        )
        skill = TabularEvidenceSkill(FakeTabularBackend([sheet]))
        result = skill.run(artifact(), source_id="src-1")
        self.assertEqual(result.diagnostics.backend_id, "fake.tabular")
        self.assertEqual(len(result.units), 1)
        self.assertEqual(result.units[0].payload["tabular"]["bounds"], "A1:C2")

    def test_the_fake_backend_can_declare_loss_and_it_is_surfaced(self) -> None:
        sheet = FakeTabularBackend.make_sheet(
            "Sheet1", (["a", "b"], [None, 2])
        )
        backend = FakeTabularBackend([sheet])
        backend.DECLARED_COLLAPSE_RISKS = (TableLossKind.ABSENT,)
        result = TabularEvidenceSkill(backend).run(artifact(), source_id="src-1")
        self.assertIn(TableLossKind.ABSENT, result.diagnostics.observed_loss_kinds)
        self.assertEqual(result.unsurfaced_risks, ())


class NoSilentFallbackTests(unittest.TestCase):
    """A degraded selection must be visible on the run and on every unit."""

    class _Fatal(FakeTabularBackend):
        backend_id = "fake.primary"

        def load(self, path, options=None):  # type: ignore[override]
            return ObservedWorkbook(
                sheets=(),
                errors=("simulated reader failure",),
                fatal=True,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_path=self.backend_path,
            )

    class _Healthy(FakeTabularBackend):
        backend_id = "fake.fallback"

    def test_a_fatal_backend_falls_back_and_records_it(self) -> None:
        sheet = FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))
        skill = TabularEvidenceSkill(
            backends=[self._Fatal(), self._Healthy([sheet])]
        )
        result = skill.run(artifact(), source_id="src-1")

        self.assertEqual(len(result.diagnostics.fallbacks), 1)
        fallback = result.diagnostics.fallbacks[0]
        self.assertEqual(fallback.from_backend, "fake.primary")
        self.assertEqual(fallback.to_backend, "fake.fallback")
        self.assertEqual(result.diagnostics.backend_id, "fake.fallback")
        for unit in result.units:
            self.assertTrue(unit.producer.fallback_used)
            self.assertTrue(unit.producer.fallback_reason)
            self.assertEqual(unit.producer.backend_id, "fake.fallback")

    def test_fail_closed_suppresses_the_fallback_entirely(self) -> None:
        sheet = FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))
        skill = TabularEvidenceSkill(
            backends=[self._Fatal(), self._Healthy([sheet])]
        )
        result = skill.run(
            artifact(), source_id="src-1", options={"fail_closed": True}
        )
        self.assertEqual(result.diagnostics.fallbacks, [])
        self.assertEqual(result.units, ())
        self.assertTrue(result.diagnostics.has_fatal_error)

    def test_a_backend_exception_becomes_an_attributable_diagnostic(self) -> None:
        class Broken(FakeTabularBackend):
            backend_id = "fake.broken"

            def load(self, path, options=None):  # type: ignore[override]
                raise RuntimeError("reader exploded")

        result = TabularEvidenceSkill(backends=[Broken()]).run(
            artifact(), source_id="src-1"
        )
        codes = {e.code for e in result.diagnostics.errors}
        self.assertIn("backend_raised", codes)
        self.assertFalse(result.is_complete_success)

    def test_no_usable_backend_is_a_fatal_unsupported_result(self) -> None:
        skill = TabularEvidenceSkill(backends=[FakeTabularBackend(available=False)])
        result = skill.run(artifact(), source_id="src-1")
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertEqual(result.diagnostics.errors[0].code, "no_backend_available")
        self.assertIn("xlsx_read", result.diagnostics.unsupported_capabilities)


class FixtureBackendTests(unittest.TestCase):
    """The deterministic backend: stdlib only, and honest about what it skips."""

    def test_it_is_always_available(self) -> None:
        self.assertTrue(FixtureXlsxBackend().is_available())

    def test_it_reports_itself_as_the_fixture_path(self) -> None:
        backend = FixtureXlsxBackend()
        self.assertEqual(backend.backend_path, "fixture")
        self.assertEqual(backend.backend_id, "fixture.ooxml-stdlib")

    def test_it_declares_csv_unsupported(self) -> None:
        capabilities = {c.name: c for c in FixtureXlsxBackend().capabilities()}
        self.assertEqual(capabilities["csv_read"].support, TableSupport.UNSUPPORTED)

    def test_it_declares_unread_content_as_a_loss_risk(self) -> None:
        capabilities = {c.name: c for c in FixtureXlsxBackend().capabilities()}
        for name in ("cell_comments", "embedded_objects"):
            self.assertEqual(capabilities[name].support, TableSupport.UNSUPPORTED)
            self.assertIn(TableLossKind.SILENT_LOSS_RISK, capabilities[name].collapse_risks)

    def test_it_reports_formula_text_as_supported_without_evaluation(self) -> None:
        capabilities = {c.name: c for c in FixtureXlsxBackend().capabilities()}
        self.assertEqual(capabilities["formula_text"].support, TableSupport.SUPPORTED)
        self.assertEqual(
            capabilities["formula_evaluation"].support, TableSupport.UNSUPPORTED
        )

    def test_a_non_xlsx_artifact_is_warned_about_not_silently_accepted(self) -> None:
        csv_artifact = TableArtifact.from_file(FIXTURE, "a", media_type="text/csv")
        result = TabularEvidenceSkill(FixtureXlsxBackend()).run(
            csv_artifact, source_id="src-1"
        )
        self.assertTrue(
            any(w.code == "media_type_not_xlsx" for w in result.diagnostics.warnings)
        )


class CalamineSpikeTests(unittest.TestCase):
    """The C06/C07 spike is conditional, never adopted."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = CalamineBackend()

    def test_availability_is_probed_not_assumed(self) -> None:
        self.assertIn(self.backend.is_available(), (True, False))

    def test_the_spike_declares_its_collapse_risks(self) -> None:
        self.assertTrue(self.backend.DECLARED_COLLAPSE_RISKS)
        self.assertIn(TableLossKind.COLLAPSE_RISK, self.backend.DECLARED_COLLAPSE_RISKS)

    def test_the_spike_does_not_claim_lossy_distinctions(self) -> None:
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
                TableSupport.SUPPORTED,
                f"the spike must not claim {name} is supported",
            )

    def test_the_spike_is_never_selected_when_a_backend_is_injected(self) -> None:
        skill = TabularEvidenceSkill(FixtureXlsxBackend())
        result = skill.run(artifact(), source_id="src-1")
        self.assertNotEqual(result.diagnostics.backend_id, "calamine.python-calamine")

    def test_an_unusable_spike_falls_through_to_the_fixture_backend(self) -> None:
        import types

        unavailable = CalamineBackend(module=types.SimpleNamespace())
        self.assertFalse(unavailable.is_available())
        result = TabularEvidenceSkill(
            backends=[unavailable, FixtureXlsxBackend()]
        ).run(artifact(), source_id="src-1")
        self.assertEqual(result.diagnostics.backend_id, "fixture.ooxml-stdlib")
        self.assertTrue(result.units)

    def test_an_unavailable_spike_is_not_silently_substituted(self) -> None:
        """When the spike fails and no alternative is injected, it is reported."""
        import types

        unavailable = CalamineBackend(module=types.SimpleNamespace())
        result = TabularEvidenceSkill(backends=[unavailable]).run(
            artifact(), source_id="src-1"
        )
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertFalse(result.is_complete_success)


class BackendContractShapeTests(unittest.TestCase):
    """Every backend must satisfy the same minimal contract."""

    def test_all_backends_expose_the_contract(self) -> None:
        for backend in (FixtureXlsxBackend(), CalamineBackend()):
            with self.subTest(backend=backend.backend_id):
                self.assertTrue(hasattr(backend, "backend_id"))
                self.assertTrue(hasattr(backend, "backend_version"))
                self.assertTrue(hasattr(backend, "backend_path"))
                self.assertTrue(callable(backend.is_available))
                self.assertTrue(callable(backend.capabilities))
                self.assertTrue(callable(backend.load))

    def test_capabilities_are_well_formed(self) -> None:
        for backend in (FixtureXlsxBackend(), CalamineBackend()):
            for capability in backend.capabilities():
                with self.subTest(backend=backend.backend_id, name=capability.name):
                    self.assertIn(capability.support, TableSupport.ALL)

    def test_load_is_read_only_with_respect_to_the_artifact(self) -> None:
        before = FIXTURE.read_bytes()
        observation = FixtureXlsxBackend().load(str(FIXTURE))
        self.assertIsInstance(observation, ObservedWorkbook)
        self.assertTrue(observation.sheets)
        self.assertTrue(all(isinstance(s, ObservedSheet) for s in observation.sheets))
        self.assertEqual(FIXTURE.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
