"""C-stage independent literal OOXML oracle and adversarial evidence mutations."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_STORED

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402
from skills.luohai.contracts import (TableArtifact, TableEvidenceUnit, TableProducer,
    TableCitationAddress, TableRunDiagnostics, TableRunResult, table_digest_bytes)
from skills.luohai.citation import CitationSelector
from skills.luohai.operators_v1 import (VerificationPolicy, RECONSTRUCT_VERIFY, ACCOUNT_LOSS)

MEDIA = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def original(value='42', extra='', formula='1+2'):
    """Literal package assembled independently of LuoHai's writer and reader."""
    parts = {
        'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Oracle" sheetId="1" r:id="r1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{NS}"><dimension ref="A1:H3"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Label</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>重复</t></is></c><c r="B2"><v>{value}</v></c><c r="C2"/><c r="E2"><f>{formula}</f><v>3</v></c><c r="F2"><v>42</v></c><c r="G2" t="e"><v>#DIV/0!</v></c><c r="H2"><f>1+2</f></c>{extra}</row><row r="3"><c r="B3" t="inlineStr"><is><t>Merged</t></is></c></row></sheetData><mergeCells><mergeCell ref="B3:C3"/></mergeCells></worksheet>'}
    data = BytesIO()
    with ZipFile(data, 'w', compression=ZIP_STORED) as z:
        for name, text in parts.items():
            # Fixed metadata makes the independent oracle bytes reproducible.
            from zipfile import ZipInfo
            z.writestr(ZipInfo(name, (2026, 1, 1, 0, 0, 0)), text.encode('utf-8'))
    return data.getvalue()


def build(raw=None):
    raw = original() if raw is None else raw
    artifact = TableArtifact('A:oracle', table_digest_bytes(raw), media_type=MEDIA,
        byte_length=len(raw), payload_bytes=raw)
    producer = TableProducer('LuoHai.TabularEvidence', 'oracle', 'fixture.ooxml-stdlib', 'oracle', 'run:oracle')
    # Evidence gold below is literal, not obtained by invoking a parser/operator.
    facts = {'A1': ('Label', 'string', None), 'A2': ('重复', 'string', None),
        'B2': (42.0, 'number', None), 'C2': (None, 'empty', None),
        'E2': (3.0, 'number', '1+2'), 'F2': (42.0, 'number', None),
        'G2': ('#DIV/0!', 'error', None), 'H2': (None, 'empty', '1+2'),
        'B3': ('Merged', 'string', None)}
    cells = []
    for row in range(1, 4):
        for col, letter in enumerate('ABCDEFGH', 1):
            ref = letter + str(row)
            value, kind, formula = facts.get(ref, (None, 'merged' if ref == 'C3' else 'absent', None))
            cells.append(dict(ref=ref, row=row, column=col, value=value, value_kind=kind,
                formula=formula, merged_from='B3' if ref == 'C3' else None, hidden=False,
                loss=['absent'] if kind in ('absent', 'merged') else (['empty'] if kind == 'empty' else []),
                notes=[], is_header=row == 1))
    block = dict(sheet_name='Oracle', sheet_index=1, region_id='region:oracle', bounds='A1:H3',
                 cells=cells, header_row=1, row_labels={}, column_headers={})
    unit = TableEvidenceUnit('unit:oracle', 'content', 'source:oracle', artifact.artifact_id,
        producer, TableCitationAddress('content_location', 'A1', 'region:oracle'),
        provenance=artifact.content_digest, payload={'tabular': block})
    return artifact, unit


def point(ref):
    return CitationSelector(region_id='region:oracle', ref=ref)


def run_for(artifact, unit):
    return TableRunResult(artifact, unit.producer.skill_id, unit.producer, (unit,),
        TableRunDiagnostics(backend_id=unit.producer.backend_id, backend_version=unit.producer.backend_version))


class VerificationAcceptance(unittest.TestCase):
    def test_independent_nonempty_source_value(self):
        a, u = build()
        out = RECONSTRUCT_VERIFY(a, u, point('B2'))
        self.assertEqual(out.status, 'verified')
        self.assertTrue(out.artifact_identity_verified)
        self.assertTrue(out.citation_address_reconstructable)
        self.assertTrue(out.stored_observations_verified)
        self.assertEqual(out.original_observations[0]['stored_or_cached_value'], 42.0)
        self.assertEqual(out.value_interpretation, 'not_verified')

    def test_wrong_digest_and_length(self):
        a, u = build()
        for bad in (replace(a, digest='0'*64), replace(a, byte_length=a.byte_length+1)):
            self.assertEqual(RECONSTRUCT_VERIFY(bad, u, point('B2')).status, 'integrity_failure')

    def test_changed_original_value_with_unchanged_cell_claim(self):
        a, u = build(original(value='99'))
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('B2')).status, 'mismatch')

    def test_changed_evidence_value_and_formula(self):
        for field, value in [('value', 777), ('formula', '9+9'), ('value_kind', 'string'), ('row', 9), ('merged_from', 'A1')]:
            with self.subTest(field=field):
                a, u = build()
                next(c for c in u.payload['tabular']['cells'] if c['ref'] == 'E2')[field] = value
                self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('E2')).status, 'mismatch')

    def test_mutated_artifact_and_provenance(self):
        a, u = build()
        for bad in (replace(u, artifact_id='other'), replace(u, provenance='sha256:wrong')):
            self.assertEqual(RECONSTRUCT_VERIFY(a, bad, point('B2')).status, 'integrity_failure')

    def test_ambiguous_selector_preserves_candidates(self):
        a, u = build()
        out = RECONSTRUCT_VERIFY(a, u, CitationSelector(region_id='region:oracle', value=42))
        self.assertEqual(out.status, 'ambiguous')
        self.assertEqual(out.citation['candidate_refs'], ['B2', 'F2'])
        self.assertFalse(out.stored_observations_verified)

    def test_duplicate_stored_address_is_ambiguous(self):
        a, u = build()
        u.payload['tabular']['cells'].append(deepcopy(u.payload['tabular']['cells'][0]))
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('A1')).status, 'ambiguous')

    def test_present_empty_absent_merged_error_and_formulas(self):
        a, u = build()
        expected = {'C2': (True, 'blank', None), 'D2': (False, 'absent', None),
            'C3': (False, 'absent', 'B3'), 'G2': (True, 'error', None),
            'E2': (True, 'number', None), 'H2': (True, 'blank', None)}
        for ref, (present, kind, merge) in expected.items():
            with self.subTest(ref=ref):
                out = RECONSTRUCT_VERIFY(a, u, point(ref))
                self.assertEqual(out.status, 'verified')
                observation = out.original_observations[0]
                self.assertEqual(observation['element_present'], present)
                self.assertEqual(observation['raw_kind'], kind)
                self.assertEqual(observation['merged_from'], merge)
        formula = RECONSTRUCT_VERIFY(a, u, point('E2')).original_observations[0]
        self.assertEqual(formula['formula_text'], '1+2')
        self.assertEqual(formula['stored_or_cached_value'], 3.0)
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('H2')).original_observations[0]['stored_or_cached_value'], None)

    def test_range_checks_every_original_coordinate(self):
        a, u = build()
        out = RECONSTRUCT_VERIFY(a, u, CitationSelector(region_id='region:oracle', ref_range='A1:H3'))
        self.assertEqual(out.status, 'verified')
        self.assertEqual(len(out.original_observations), 24)
        self.assertEqual(out.original_observations[-1]['ref'], 'H3')

    def test_missing_stored_present_cell_is_not_absent(self):
        a, u = build()
        u.payload['tabular']['cells'] = [c for c in u.payload['tabular']['cells'] if c['ref'] != 'C2']
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('C2')).status, 'mismatch')

    def test_missing_vs_empty_mutation_detected(self):
        a, u = build()
        next(c for c in u.payload['tabular']['cells'] if c['ref'] == 'C2')['value_kind'] = 'absent'
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('C2')).status, 'mismatch')

    def test_verification_levels_only_claim_checked_work(self):
        a, u = build()
        for level in ('artifact', 'address'):
            out = RECONSTRUCT_VERIFY(a, u, point('B2'), VerificationPolicy(level))
            self.assertEqual(out.status, 'verified')
            self.assertFalse(out.stored_observations_verified)
            self.assertEqual(out.citation_address_reconstructable, level == 'address')
        out = RECONSTRUCT_VERIFY(a, u, point('E2'), VerificationPolicy('interpretation'))
        self.assertEqual(out.status, 'unsupported')
        self.assertTrue(out.stored_observations_verified)
        self.assertEqual(out.value_interpretation, 'unsupported')

    def test_unavailable_original(self):
        a, u = build()
        self.assertEqual(RECONSTRUCT_VERIFY(replace(a, payload_bytes=None), u, point('B2')).status, 'unavailable')

    def test_unsupported_backend(self):
        a, u = build()
        u.producer = replace(u.producer, backend_id='calamine.python-calamine')
        out = RECONSTRUCT_VERIFY(a, u, point('B2'))
        self.assertEqual(out.status, 'unsupported')
        self.assertTrue(out.citation_address_reconstructable)
        self.assertFalse(out.stored_observations_verified)

    def test_corrupt_original_package(self):
        a, u = build(b'not a zip file')
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('B2')).status, 'corrupt')

    def test_unsupported_duplicate_original_coordinate(self):
        a, u = build(original(extra='<c r="B2"><v>42</v></c>'))
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('B2')).status, 'unsupported')

    def test_formula_text_change_in_original_detected(self):
        a, u = build(original(formula='2+1'))
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('E2')).status, 'mismatch')

    def test_invalid_and_outside_selector(self):
        a, u = build()
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('Z99')).status, 'unresolved')
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, CitationSelector(ref='B2', ref_range='B2:C2')).status, 'invalid_input')
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, CitationSelector(ref='B2', value=99)).status, 'unsupported')
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, CitationSelector(ref_range='A1:XFD1048576')).status, 'unsupported')

    def test_deterministic_nonmutating(self):
        a, u = build()
        before = deepcopy((a, u))
        self.assertEqual(RECONSTRUCT_VERIFY(a, u, point('B2')), RECONSTRUCT_VERIFY(a, u, point('B2')))
        self.assertEqual((a, u), before)

    def test_canonical_extraction_integration(self):
        from skills.luohai import FixtureXlsxBackend, TabularEvidenceSkill
        artifact = TableArtifact.from_file(_bootstrap.FIXTURE_PATH, 'A:integration')
        run = TabularEvidenceSkill(FixtureXlsxBackend()).run(artifact, source_id='source:integration')
        units = [u for u in run.units if 'tabular' in u.payload]
        self.assertTrue(units)
        for unit in units:
            with self.subTest(unit=unit.unit_id):
                block = unit.payload['tabular']
                selector = CitationSelector(region_id=block['region_id'], ref_range=block['bounds'])
                out = RECONSTRUCT_VERIFY(artifact, unit, selector)
                self.assertEqual(out.status, 'verified', out.diagnostics)

    def test_unsupported_cell_encoding_and_shared_formula(self):
        for extra in ('<c r="D2" t="mystery"><v>42</v></c>',
                      '<c r="D2" t="b"><v>not-a-boolean</v></c>',
                      '<c r="D2"><f t="shared" si="0"/><v>3</v></c>'):
            a, u = build(original(extra=extra))
            out = RECONSTRUCT_VERIFY(a, u, point('B2'))
            self.assertEqual(out.status, 'unsupported')


class LossAcceptance(unittest.TestCase):
    def test_repeated_declarations_not_independent_events(self):
        a, u = build()
        u.loss = ('empty', 'empty', 'absent')
        run = run_for(a, u)
        run.units = (u, deepcopy(u))
        out = ACCOUNT_LOSS(run)
        self.assertEqual(out.observed_losses_by_kind, {'absent': 1, 'empty': 1})
        self.assertEqual(len(out.unit_losses), 1)
        self.assertFalse(out.complete_success_justified)

    def test_declared_collapse_risks_not_surfaced(self):
        a, u = build()
        run = run_for(a, u)
        run.diagnostics.known_collapse_risks = ['collapse_risk', 'collapse_risk']
        out = ACCOUNT_LOSS(run)
        self.assertEqual(out.unsurfaced_risks, ('collapse_risk',))
        self.assertFalse(out.complete_success_justified)

    def test_unsupported_exemption_cannot_hide_risk(self):
        a, u = build()
        run = run_for(a, u)
        run.diagnostics.known_collapse_risks = ['collapse_risk']
        run.diagnostics.unsupported_capabilities = ['formula_text']
        self.assertEqual(run.unsurfaced_risks, ())
        out = ACCOUNT_LOSS(run)
        self.assertEqual(out.unsurfaced_risks, ('collapse_risk',))
        self.assertEqual(out.unsupported_capabilities, ('formula_text',))

    def test_conflicting_producer_metadata(self):
        for target in ('unit', 'run'):
            a, u = build()
            run = run_for(a, u)
            if target == 'unit':
                u.producer = replace(u.producer, backend_id='fake.backend')
            else:
                run.diagnostics.backend_version = 'conflicting-version'
            out = ACCOUNT_LOSS(run)
            self.assertEqual(out.status, 'inconsistent')
            self.assertFalse(out.complete_success_justified)

    def test_provenance_and_duplicate_unit_conflicts(self):
        a, u = build()
        run = run_for(a, u)
        duplicate = replace(u, provenance='sha256:other')
        run.units = (u, duplicate)
        self.assertIn('conflicting_duplicate_unit:unit:oracle', ACCOUNT_LOSS(run).inconsistencies)
        run.units = (duplicate,)
        self.assertIn('unit_provenance_mismatch:unit:oracle', ACCOUNT_LOSS(run).inconsistencies)

    def test_absence_of_losses_is_not_workbook_completeness(self):
        a, u = build()
        u.payload = {}
        out = ACCOUNT_LOSS(run_for(a, u))
        self.assertEqual(out.workbook_observation_completeness, 'unknown')
        # Contract-level result only: no assertion that every source cell was read.
        self.assertTrue(out.declared_complete_success)
        self.assertTrue(out.complete_success_justified)

    def test_cell_losses_cannot_disappear_from_accounting(self):
        a, u = build()
        out = ACCOUNT_LOSS(run_for(a, u))
        self.assertEqual(out.observed_losses_by_kind, {'absent': 1, 'empty': 1})
        self.assertIn('cell_losses_missing_from_unit_summary:unit:oracle', out.inconsistencies)
        self.assertFalse(out.complete_success_justified)

    def test_empty_run_and_unknown_loss_state(self):
        a, u = build()
        run = run_for(a, u)
        run.units = ()
        self.assertFalse(ACCOUNT_LOSS(run).complete_success_justified)
        run.units = (replace(u, loss=('unknown',)),)
        self.assertIn('unresolved_loss:unknown', ACCOUNT_LOSS(run).unresolved_states)

    def test_accounting_never_calls_mutating_downgrade(self):
        a, u = build()
        run = run_for(a, u)
        run.diagnostics.known_collapse_risks = ['collapse_risk']
        before = deepcopy(run)
        with patch.object(TableRunResult, 'downgrade_for_declared_risk', side_effect=AssertionError('mutation forbidden')):
            out = ACCOUNT_LOSS(run)
        self.assertEqual(run, before)
        self.assertEqual(run.diagnostics.warnings, [])
        self.assertEqual(out, ACCOUNT_LOSS(run))

    def test_returned_diagnostics_do_not_alias_input(self):
        a, u = build()
        run = run_for(a, u)
        out = ACCOUNT_LOSS(run)
        out.diagnostics['warnings'].append({'code': 'altered'})
        self.assertEqual(run.diagnostics.warnings, [])

    def test_non_JSON_backend_value_is_explicit_unknown(self):
        from datetime import date
        a, u = build()
        u.content = date(2026, 1, 1)
        out = ACCOUNT_LOSS(run_for(a, u))
        self.assertEqual(out.status, 'unknown')
        self.assertIsNone(out.input_digest)
        self.assertFalse(out.complete_success_justified)
        self.assertEqual(out.unresolved_states, ('unsupported_non_JSON_run_observations',))

    def test_missing_run_producer_is_explicit_unknown(self):
        a, u = build()
        run = run_for(a, u)
        run.producer = None
        out = ACCOUNT_LOSS(run)
        self.assertEqual(out.status, 'unknown')
        self.assertFalse(out.complete_success_justified)


if __name__ == '__main__':
    unittest.main()
