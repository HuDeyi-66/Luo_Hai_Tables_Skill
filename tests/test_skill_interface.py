"""T4 -- the minimal Skill interface.

The M1 exit condition is "the interface can be called by a fake adapter". These
tests prove it, and then prove the *fail-closed* properties that make the
interface worth having:

* a missing source identity is an error, not an invented value;
* an unavailable backend produces an explicit unsupported/error result;
* a fallback is recorded on both the run and every unit it produced;
* a backend that declares a collapse risk cannot yield a clean success unless
  the risk is surfaced.
"""

from __future__ import annotations

import sys
import types
import unittest
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _bootstrap  # noqa: E402

from core.artifact import Artifact  # noqa: E402
from core.evidence import LossKind, UnitClass  # noqa: E402
from core.skill_result import Capability, Support  # noqa: E402
from skills.luohai.backends import (  # noqa: E402
    CalamineBackend,
    FakeTabularBackend,
    FixtureXlsxBackend,
)
from skills.luohai import TabularEvidenceSkill  # noqa: E402


def fixture_artifact() -> Artifact:
    return Artifact.from_file(_bootstrap.FIXTURE_PATH, "art-fixture")


class FakeBackendInterfaceTests(unittest.TestCase):
    """M1: the interface is callable before any real reader exists."""

    def setUp(self) -> None:
        self.sheet = FakeTabularBackend.make_sheet(
            "Sheet1",
            (
                ["Port", "2023", "2024"],
                ["Shanghai", 10, 42],
                ["Ningbo", 11, 42],
            ),
        )
        self.backend = FakeTabularBackend([self.sheet])
        self.skill = TabularEvidenceSkill(self.backend)

    def test_fake_backend_produces_units_and_a_result(self) -> None:
        result = self.skill.run(fixture_artifact(), source_id="src-1")
        self.assertEqual(len(result.units), 1)
        unit = result.units[0]
        self.assertEqual(unit.unit_class, UnitClass.CONTENT)
        self.assertEqual(unit.payload["tabular"]["bounds"], "A1:C3")
        self.assertEqual(unit.payload["tabular"]["sheet_name"], "Sheet1")
        self.assertEqual(unit.producer.backend_id, "fake.tabular")

    def test_producer_and_run_identity_are_recorded(self) -> None:
        result = self.skill.run(fixture_artifact(), source_id="src-1")
        self.assertEqual(result.skill_id, "LuoHai.TabularEvidence")
        self.assertTrue(result.invocation_id)
        self.assertTrue(result.started_at)
        self.assertTrue(result.finished_at)
        self.assertEqual(result.units[0].producer.run_id, result.producer.run_id)

    def test_capability_statement_names_supported_and_unsupported(self) -> None:
        capabilities = {c.name: c for c in self.skill.capabilities()}
        self.assertIn("tabular_evidence_units", capabilities)
        self.assertEqual(capabilities["tabular_evidence_units"].support, Support.SUPPORTED)
        self.assertEqual(capabilities["csv_read"].support, Support.UNSUPPORTED)
        self.assertEqual(
            capabilities["confidence_scoring"].support, Support.UNSUPPORTED
        )

    def test_skill_reports_unsupported_capabilities_in_diagnostics(self) -> None:
        result = self.skill.run(fixture_artifact(), source_id="src-1")
        self.assertIn("csv_read", result.diagnostics.unsupported_capabilities)

    def test_describe_is_machine_readable(self) -> None:
        described = self.skill.describe()
        self.assertEqual(described["skill_id"], "LuoHai.TabularEvidence")
        self.assertTrue(any(c["name"] == "csv_read" for c in described["capabilities"]))


class FailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = TabularEvidenceSkill(FakeTabularBackend())

    def test_missing_source_identity_is_a_fatal_error(self) -> None:
        result = self.skill.run(fixture_artifact())
        self.assertEqual(result.units, ())
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertEqual(result.diagnostics.errors[0].code, "missing_source_identity")
        self.assertFalse(result.is_complete_success)

    def test_source_object_may_supply_the_identity(self) -> None:
        class Source:
            source_id = "src-from-object"

        skill = TabularEvidenceSkill(
            FakeTabularBackend([FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))])
        )
        result = skill.run(fixture_artifact(), source=Source())
        self.assertEqual(result.units[0].source_id, "src-from-object")

    def test_artifact_without_a_location_fails_closed(self) -> None:
        artifact = Artifact(artifact_id="a", digest="d" * 64, location=None)
        result = self.skill.run(artifact, source_id="src-1")
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertEqual(result.diagnostics.errors[0].code, "artifact_has_no_location")

    def test_artifact_digest_mismatch_fails_closed_before_backend_use(self) -> None:
        artifact = Artifact(
            artifact_id="tampered",
            digest="0" * 64,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            location=str(_bootstrap.FIXTURE_PATH),
        )
        result = self.skill.run(artifact, source_id="src-1")
        self.assertEqual(result.units, ())
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertEqual(
            result.diagnostics.errors[0].code, "artifact_integrity_mismatch"
        )

    def test_post_registration_mutation_fails_closed(self) -> None:
        target = _bootstrap.artifacts_dir() / f"integrity_mutation_{os.getpid()}.xlsx"
        target.write_bytes(_bootstrap.FIXTURE_PATH.read_bytes())
        try:
            artifact = Artifact.from_file(target, "mutated")
            target.write_bytes(target.read_bytes() + b"changed-after-registration")
            result = self.skill.run(artifact, source_id="src-1")
            self.assertEqual(result.units, ())
            self.assertTrue(result.diagnostics.has_fatal_error)
            self.assertEqual(
                result.diagnostics.errors[0].code, "artifact_integrity_mismatch"
            )
        finally:
            target.unlink(missing_ok=True)

    def test_non_xlsx_media_type_is_warned_not_silently_accepted(self) -> None:
        artifact = Artifact.from_file(
            _bootstrap.FIXTURE_PATH, "a", media_type="text/csv"
        )
        result = self.skill.run(artifact, source_id="src-1")
        self.assertTrue(
            any(w.code == "media_type_not_xlsx" for w in result.diagnostics.warnings)
        )

    def test_backend_that_is_unavailable_reports_unsupported(self) -> None:
        backend = FakeTabularBackend(available=False)
        skill = TabularEvidenceSkill(backends=[backend])
        result = skill.run(fixture_artifact(), source_id="src-1")
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertEqual(result.diagnostics.errors[0].code, "no_backend_available")
        self.assertIn("xlsx_read", result.diagnostics.unsupported_capabilities)

    def test_backend_load_failure_becomes_diagnostics_not_an_exception(self) -> None:
        class BrokenBackend(FakeTabularBackend):
            backend_id = "fake.broken"

            def load(self, path, options=None):  # type: ignore[override]
                raise RuntimeError("reader exploded")

        skill = TabularEvidenceSkill(backends=[BrokenBackend()])
        result = skill.run(fixture_artifact(), source_id="src-1")
        self.assertEqual(result.units, ())
        self.assertTrue(result.diagnostics.has_fatal_error)
        codes = {e.code for e in result.diagnostics.errors}
        self.assertIn("backend_raised", codes)
        self.assertFalse(result.is_complete_success)

    def test_no_units_is_warned(self) -> None:
        result = self.skill.run(fixture_artifact(), source_id="src-1")
        self.assertEqual(result.units, ())
        self.assertTrue(
            any(w.code == "no_units_emitted" for w in result.diagnostics.warnings)
        )


class NoSilentFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.artifact = fixture_artifact()

    def test_fatal_backend_failure_falls_back_and_records_it(self) -> None:
        sheet = FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))

        class FailingBackend(FakeTabularBackend):
            backend_id = "fake.primary"

            def load(self, path, options=None):  # type: ignore[override]
                return super().load(path, options).__class__(
                    sheets=(),
                    errors=("simulated reader failure",),
                    fatal=True,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    backend_path=self.backend_path,
                )

        class HealthyBackend(FakeTabularBackend):
            backend_id = "fake.fallback"

        skill = TabularEvidenceSkill(backends=[FailingBackend(), HealthyBackend([sheet])])
        result = skill.run(self.artifact, source_id="src-1")

        self.assertEqual(len(result.diagnostics.fallbacks), 1)
        fallback = result.diagnostics.fallbacks[0]
        self.assertEqual(fallback.from_backend, "fake.primary")
        self.assertEqual(fallback.to_backend, "fake.fallback")
        self.assertEqual(result.diagnostics.backend_id, "fake.fallback")
        self.assertTrue(result.units)
        self.assertTrue(all(u.producer.fallback_used for u in result.units))
        self.assertTrue(all(u.producer.fallback_reason for u in result.units))
        self.assertTrue(all(u.producer.backend_id == "fake.fallback" for u in result.units))

    def test_fail_closed_option_suppresses_the_fallback(self) -> None:
        sheet = FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))

        class FailingBackend(FakeTabularBackend):
            backend_id = "fake.primary"

            def load(self, path, options=None):  # type: ignore[override]
                return super().load(path, options).__class__(
                    sheets=(),
                    errors=("simulated reader failure",),
                    fatal=True,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    backend_path=self.backend_path,
                )

        class HealthyBackend(FakeTabularBackend):
            backend_id = "fake.fallback"

        skill = TabularEvidenceSkill(backends=[FailingBackend(), HealthyBackend([sheet])])
        result = skill.run(self.artifact, source_id="src-1", options={"fail_closed": True})

        self.assertEqual(result.diagnostics.fallbacks, [])
        self.assertEqual(result.units, ())
        self.assertTrue(result.diagnostics.has_fatal_error)

    def test_fixture_is_the_environment_independent_default(self) -> None:
        skill = TabularEvidenceSkill()
        candidates = skill._candidate_backends({})  # noqa: SLF001 - order is the contract
        self.assertEqual([b.backend_id for b in candidates], ["fixture.ooxml-stdlib"])

    def test_fixture_backend_can_be_injected_explicitly(self) -> None:
        skill = TabularEvidenceSkill(FixtureXlsxBackend())
        result = skill.run(self.artifact, source_id="src-1")
        self.assertEqual(result.diagnostics.backend_id, "fixture.ooxml-stdlib")
        self.assertEqual(result.diagnostics.fallbacks, [])


class DeclaredRiskPropagationTests(unittest.TestCase):
    """The mechanism that stops a silent-loss fixture reporting clean success."""

    def test_declared_risk_unsurfaced_downgrades_the_result(self) -> None:
        backend = FakeTabularBackend(
            [FakeTabularBackend.make_sheet("S", (["a", "b"], [1, 2]))],
            capabilities=(
                # Declares it may collapse errors, and surfaces nothing.
                Capability(
                    name="error_state",
                    support=Support.UNSUPPORTED,
                    detail="may collapse",
                    collapse_risks=(LossKind.EMPTY,),
                ),
            ),
        )
        backend.DECLARED_COLLAPSE_RISKS = (LossKind.EMPTY,)
        skill = TabularEvidenceSkill(backend)

        result = skill.run(fixture_artifact(), source_id="src-1")
        self.assertFalse(result.is_complete_success)
        self.assertEqual(result.unsurfaced_risks, (LossKind.EMPTY,))
        self.assertTrue(
            any(
                w.code == f"declared_risk_not_surfaced:{LossKind.EMPTY}"
                for w in result.diagnostics.warnings
            )
        )

    def test_declared_risk_surfaced_by_a_cell_keeps_the_run_attributable(self) -> None:
        sheet = FakeTabularBackend.make_sheet(
            "S",
            (
                ["a", "b"],
                [None, 2],
            ),
        )
        backend = FakeTabularBackend([sheet])
        backend.DECLARED_COLLAPSE_RISKS = (LossKind.ABSENT,)
        skill = TabularEvidenceSkill(backend)

        result = skill.run(fixture_artifact(), source_id="src-1")
        # The declaration is satisfied, so nothing is downgraded...
        self.assertEqual(result.unsurfaced_risks, ())
        self.assertTrue(result.has_no_fatal_condition)
        # ...but the absent cell was still observed, so this is not a
        # lossless read and must not be reported as a complete success.
        self.assertFalse(result.is_complete_success)
        self.assertIn(LossKind.ABSENT, result.diagnostics.observed_loss_kinds)


class FallbackProofWithBindingDisabledTests(unittest.TestCase):
    """Proves the fallback path when the locked binding cannot be used."""

    def test_unavailable_calamine_selects_the_fixture_backend(self) -> None:
        # A module object that lacks the reader entry point stands in for an
        # absent or unusable binding. Injection is used rather than patching
        # `importlib`, because the real module may well be importable here.
        stub = types.SimpleNamespace()
        unavailable = CalamineBackend(module=stub)
        self.assertFalse(unavailable.is_available())
        self.assertNotEqual(unavailable.capabilities()[0].support, Support.SUPPORTED)

        skill = TabularEvidenceSkill(backends=[unavailable, FixtureXlsxBackend()])
        result = skill.run(fixture_artifact(), source_id="src-1")
        self.assertEqual(result.diagnostics.backend_id, "fixture.ooxml-stdlib")
        self.assertGreater(len(result.units), 0)
        self.assertEqual(
            result.diagnostics.considered_backends,
            ["calamine.python-calamine", "fixture.ooxml-stdlib"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
