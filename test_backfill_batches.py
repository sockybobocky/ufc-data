import tempfile
import unittest
from pathlib import Path
from backfill_batches import run_batches
from test_ufcstats_parser import fixture, URL

class BatchTests(unittest.TestCase):
    def test_aggregation_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'source.csv'
            source.write_text('FIGHT_URL,EVENT,DATE\n'+''.join(f'{URL}{i},Test,2026-01-01\n' for i in range(5)))
            output = Path(temp)/'output'
            report = run_batches(source,output,lambda _:fixture(),limit=2,batches=3)
            self.assertEqual(report['selected'],5)
            self.assertEqual(report['repaired'],5)
            self.assertEqual(report['next_offset'],5)
            def forbidden(_):
                self.fail('Resume fetched a completed record')
            self.assertEqual(run_batches(source,output,forbidden,limit=2,batches=3,resume=True)['fetched_this_run'],0)
            with self.assertRaises(ValueError):
                run_batches(source,output,forbidden,limit=1,batches=3,resume=True)

    def test_invalid_batch_count(self):
        for batches in (0,6):
            with self.assertRaises(ValueError):
                run_batches('unused','unused',lambda _:None,batches=batches)

if __name__ == '__main__':
    unittest.main()
