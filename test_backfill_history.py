import tempfile
import unittest
from pathlib import Path
from backfill_history import run, select
from test_ufcstats_parser import fixture, URL

class BackfillTests(unittest.TestCase):
    def test_nonoverlapping_deterministic_batches(self):
        rows = [{'FIGHT_URL':str(i),'OUTCOME':'W/L','TIME':'1:00'} for i in range(120)]
        self.assertEqual(select(rows,100),rows[:100])
        self.assertEqual(select(rows,20,100),rows[100:])

    def test_invalid_bounds_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source,output = self.setup_paths(root)
            for limit,offset in ((101,0),(0,0),(5,-1),(5,100)):
                with self.subTest(limit=limit,offset=offset),self.assertRaises(ValueError):
                    run(source,output,lambda _:fixture(),limit=limit,offset=offset)

    def setup_paths(self, root):
        source = Path(root)/'source.csv'
        source.write_text('FIGHT_URL,EVENT,DATE\n'+URL+',Test,2026-01-01\n')
        return source,Path(root)/'output'

    def test_resume_without_fetch(self):
        with tempfile.TemporaryDirectory() as root:
            source,output = self.setup_paths(root)
            self.assertEqual(run(source,output,lambda _:fixture())['repaired'],1)
            def forbidden(_):
                self.fail('Resume fetched a completed fight')
            self.assertEqual(run(source,output,forbidden,resume=True)['fetched_this_run'],0)

    def test_source_change_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source,output = self.setup_paths(root)
            run(source,output,lambda _:fixture())
            source.write_text(source.read_text()+'\n')
            with self.assertRaises(ValueError):
                run(source,output,lambda _:fixture(),resume=True)

    def test_historical_quarantine_preserves_page(self):
        with tempfile.TemporaryDirectory() as root:
            source,output = self.setup_paths(root)
            report = run(source,output,lambda _:fixture(time_format='1 Rnd + OT (12-3)'))
            self.assertEqual(report['quarantined'],1)
            self.assertEqual(report['failed'],0)
            self.assertEqual(len(list((output/'checkpoints').glob('*.html'))),1)

    def test_failed_retry_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            source,output = self.setup_paths(root)
            self.assertEqual(run(source,output,lambda _:'invalid')['failed'],1)
            self.assertEqual(run(source,output,lambda _:fixture(),resume=True)['failed'],1)
            self.assertEqual(run(source,output,lambda _:fixture(),resume=True,retry_failed=True)['repaired'],1)

    def test_incomplete_rounds_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source,output = self.setup_paths(root)
            self.assertEqual(run(source,output,lambda _:fixture(with_round=False))['failed'],1)

if __name__ == '__main__':
    unittest.main()
