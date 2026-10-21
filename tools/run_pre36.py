"""Small synthetic showcase and retained native safety modules; no archive dependency."""
import argparse,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SELECTION={'test_operators_v1': ['VerificationAcceptance.test_canonical_extraction_integration', 'VerificationAcceptance.test_independent_nonempty_source_value', 'VerificationAcceptance.test_wrong_digest_and_length', 'VerificationAcceptance.test_ambiguous_selector_preserves_candidates', 'VerificationAcceptance.test_missing_vs_empty_mutation_detected', 'LossAcceptance.test_cell_losses_cannot_disappear_from_accounting', 'LossAcceptance.test_absence_of_losses_is_not_workbook_completeness', 'LossAcceptance.test_missing_run_producer_is_explicit_unknown']}
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['showcase','essential'],nargs='?',default='showcase');a=p.parse_args()
 sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
 suite=unittest.TestSuite()
 for module,cases in SELECTION.items():
  if '/' in module:
   directory,name=module.rsplit('/',1);sys.path.insert(0,str(ROOT/directory));module=name
  if a.mode=='essential':suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
  else:
   for case in cases:suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module+'.'+case))
 result=unittest.TextTestRunner(verbosity=1).run(suite)
 print(json.dumps({'mode':a.mode,'ran':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}))
 return 0 if result.wasSuccessful() and not result.skipped else 1
if __name__=='__main__':raise SystemExit(main())
