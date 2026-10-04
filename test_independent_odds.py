import ast
import json
import tempfile
import unittest
from pathlib import Path
from export_odds import collect
from test_odds_export import fixture,Session,NOW

class IndependentOdds(unittest.TestCase):
    def test_odds_only_import_has_no_browser_or_history_dependency(self):
        source=(Path(__file__).parent/'export_odds.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertEqual(imports,['odds_export','odds_budget'])
        self.assertNotIn('scrape_ufc_data',source)
    def test_missing_key_records_failure_without_provider_request(self):
        with tempfile.TemporaryDirectory() as folder:
            session=Session(fixture());status=collect(session,'',folder)
            self.assertEqual(session.calls,[]);self.assertEqual(status['state'],'failed')
            self.assertEqual(json.loads((Path(folder)/'ufc_odds_status.json').read_text())['state'],'failed')
    def test_successful_collection_does_not_touch_history(self):
        with tempfile.TemporaryDirectory() as folder:
            history=Path(folder)/'ufc_fight_results.csv';history.write_bytes(b'original history')
            self.assertEqual(collect(Session(fixture()),'fake-key',folder)['state'],'success')
            self.assertEqual(history.read_bytes(),b'original history')
    def test_history_failure_does_not_prevent_independent_collection(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'scraper_repair_errors.json').write_text('[{"reason":"historical failure"}]')
            self.assertEqual(collect(Session(fixture()),'fake-key',folder)['state'],'success')
    def test_history_workflow_skips_odds_and_retains_failure_report(self):
        s=(Path(__file__).parent/'.github/workflows/update.yml').read_text(encoding='utf-8')
        self.assertIn('--skip-odds',s)
        self.assertIn('if: failure()',s)
        self.assertIn('scraper_repair_errors.json',s)
        self.assertIn('actions/upload-artifact@v4',s)
        self.assertIn('git pull --rebase origin main',s)
    def test_odds_workflow_has_narrow_publication(self):
        s=(Path(__file__).parent/'.github/workflows/update-odds.yml').read_text(encoding='utf-8')
        self.assertNotIn('scrape_ufc_data.py',s)
        self.assertNotIn('train_model',s)
        self.assertNotIn('git add *.csv',s)
        self.assertIn('secrets.ODDS_API_KEY',s)
        self.assertIn('cancel-in-progress: false',s)
    def test_scraper_flag_removes_only_optional_odds_call(self):
        tree=ast.parse((Path(__file__).parent/'scrape_ufc_data.py').read_text(encoding='utf-8'))
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        guarded=[n for n in ast.walk(main) if isinstance(n,ast.If) and '--skip-odds' in ast.unparse(n.test)]
        self.assertEqual(len(guarded),1)
        calls=[n.func.id for n in ast.walk(guarded[0]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
        self.assertEqual(calls,['fetch_betting_odds'])

if __name__=='__main__':unittest.main()
