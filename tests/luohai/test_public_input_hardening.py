"""Published byte/path requirements preserve OOXML integrity and native evidence."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import _bootstrap
from skills.luohai import TableArtifact, TabularEvidenceSkill, run_tabular_evidence, workbook_artifact

class PublicInputHardening(unittest.TestCase):
    def payload(self):return (_bootstrap.PROJECT_ROOT/'fixtures/generated/luohai_tabular_controlled.xlsx').read_bytes()
    def test_bytes_and_file_extraction_have_identical_native_units(self):
        raw=self.payload()
        memory=run_tabular_evidence(raw,artifact_id='same',source_id='synthetic')
        file=run_tabular_evidence(_bootstrap.PROJECT_ROOT/'fixtures/generated/luohai_tabular_controlled.xlsx',artifact_id='same',source_id='synthetic')
        self.assertTrue(memory.units)
        self.assertFalse(memory.diagnostics.has_fatal_error)
        self.assertEqual([u.payload for u in memory.units],[u.payload for u in file.units])
        self.assertTrue(memory.artifact.verify_bytes(raw))
        self.assertTrue(all(u.provenance==memory.artifact.content_digest for u in memory.units))
        self.assertIsNone(memory.artifact.location)
        self.assertNotIn('payload_bytes',memory.artifact.as_dict())
        json.dumps(memory.as_dict())
    def test_memory_digest_mismatch_emits_no_units(self):
        artifact=workbook_artifact(self.payload());artifact.digest='0'*64
        result=TabularEvidenceSkill().run(artifact,source_id='synthetic')
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertFalse(result.units)
    def test_missing_file_serializes_without_fabricated_digest(self):
        result=run_tabular_evidence(_bootstrap.PROJECT_ROOT/'artifacts/never-existing-input.xlsx')
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertFalse(result.units)
        self.assertFalse(result.is_complete_success)
        self.assertIsNone(result.artifact)
        self.assertIsNone(json.loads(json.dumps(result.as_dict()))['artifact'])
    def test_permission_error_becomes_typed_failure(self):
        with patch.object(TableArtifact,'from_file',side_effect=PermissionError('synthetic denied input')):
            result=run_tabular_evidence(Path('denied.xlsx'))
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertEqual(result.diagnostics.errors[0].code,'artifact_input_unreadable')
    def test_non_zip_bytes_are_not_an_empty_success(self):
        result=run_tabular_evidence(b'not-an-xlsx',source_id='synthetic')
        self.assertTrue(result.diagnostics.has_fatal_error)
        self.assertFalse(result.units)
        self.assertFalse(result.is_complete_success)
    def test_empty_bytes_are_a_registered_but_unreadable_artifact(self):
        result=run_tabular_evidence(b'',source_id='synthetic')
        self.assertIsNotNone(result.artifact)
        self.assertTrue(result.artifact.verify_bytes(b''))
        self.assertTrue(result.diagnostics.has_fatal_error)

if __name__=='__main__':unittest.main()
