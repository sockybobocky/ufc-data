import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from run_scraper_with_diagnostics import run, STAGES


class DiagnosticsTests(unittest.TestCase):
    def test_every_wrapped_phase_preserves_exception_and_restores_function(self):
        for name, phase in STAGES.items():
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                error = RuntimeError('secret=DO_NOT_EXPORT')
                def fail(): raise error
                scraper = SimpleNamespace(**{name: fail})
                scraper.main = lambda: getattr(scraper, name)()
                path = Path(directory) / 'diagnostics.json'
                with self.assertRaises(RuntimeError) as caught: run(scraper, path)
                self.assertIs(caught.exception, error)
                self.assertIs(getattr(scraper, name), fail)
                report = json.loads(path.read_text())
                self.assertEqual(report['first_failure']['phase'], phase)
                self.assertEqual(report['state'], 'failed')
                self.assertNotIn('DO_NOT_EXPORT', path.read_text())

    def test_cleanup_does_not_replace_original_failure_stage(self):
        scraper = SimpleNamespace()
        def fail(): raise ValueError('parse detail')
        scraper.scrape_events_and_fights = fail
        scraper.close_browser = lambda: None
        def main():
            try: scraper.scrape_events_and_fights()
            finally: scraper.close_browser()
        scraper.main = main
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            with self.assertRaises(ValueError): run(scraper, path)
            report = json.loads(path.read_text())
            self.assertEqual(report['phase'], 'browser_cleanup')
            self.assertEqual(report['first_failure']['phase'], 'historical_events_and_fights')

    def test_success_and_arguments_are_preserved(self):
        scraper = SimpleNamespace()
        seen = []
        scraper.scrape_events_and_fights = lambda state, full=False: seen.append((state, full))
        scraper.main = lambda: scraper.scrape_events_and_fights({'marker': 1}, full=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            run(scraper, path)
            report = json.loads(path.read_text())
            self.assertEqual(seen, [({'marker': 1}, True)])
            self.assertEqual(report['state'], 'completed')
            self.assertIsNone(report['first_failure'])

    def test_main_initialization_error_and_system_exit_stay_failures(self):
        for error in (ValueError('init'), SystemExit(7), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                def main(): raise error
                path = Path(directory) / 'report.json'
                with self.assertRaises(type(error)): run(SimpleNamespace(main=main), path)
                self.assertEqual(json.loads(path.read_text())['first_failure']['phase'], 'main_initialization')

    def test_cli_delegates_flags_and_preserves_exit_status(self):
        import subprocess, sys, shutil
        runner = Path(__file__).with_name('run_scraper_with_diagnostics.py')
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                shutil.copyfile(runner, folder / runner.name)
                statement = 'raise RuntimeError("private-details")' if failure else 'return None'
                source = 'import sys,json\nfrom pathlib import Path\ndef scrape_events_and_fights():\n '+statement+'\ndef main():\n Path("args.json").write_text(json.dumps(sys.argv[1:]))\n scrape_events_and_fights()\n'
                (folder / 'scrape_ufc_data.py').write_text(source)
                (folder / 'ufc_fight_results.csv').write_text('sentinel')
                result = subprocess.run([sys.executable, runner.name, '--full', '--skip-odds'], cwd=folder, capture_output=True, text=True)
                self.assertEqual(result.returncode != 0, failure)
                self.assertEqual(json.loads((folder / 'args.json').read_text()), ['--full', '--skip-odds'])
                report = folder / 'scraper_run_diagnostics.json'
                self.assertEqual(json.loads(report.read_text())['state'], 'failed' if failure else 'completed')
                self.assertNotIn('private-details', report.read_text())
                self.assertEqual((folder / 'ufc_fight_results.csv').read_text(), 'sentinel')

    def test_report_write_error_cannot_hide_scraper_failure(self):
        error = RuntimeError('original')
        def main(): raise error
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as caught:
                run(SimpleNamespace(main=main), Path(directory))
            self.assertIs(caught.exception, error)


if __name__ == '__main__': unittest.main()
