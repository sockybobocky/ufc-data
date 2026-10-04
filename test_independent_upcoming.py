import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from export_upcoming import collect
from test_upcoming_parser import UpcomingParser
class IndependentUpcoming(unittest.TestCase):
    def test_success_only_touches_upcoming_generation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=root/'ufc_fight_results.csv';history.write_bytes(b'untouched')
            scraper=SimpleNamespace(init_browser=Mock(),close_browser=Mock(),scrape_upcoming_events=Mock(return_value=UpcomingParser().parse()))
            report=collect(scraper,root)
            self.assertEqual(report['state'],'success');self.assertEqual(history.read_bytes(),b'untouched')
            self.assertEqual(report['sha256'],hashlib.sha256((root/'ufc_upcoming_events.csv').read_bytes()).hexdigest())
            scraper.close_browser.assert_called_once()
    def test_failure_preserves_previous_card_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);card=root/'ufc_upcoming_events.csv';card.write_bytes(b'prior verified generation')
            scraper=SimpleNamespace(init_browser=Mock(),close_browser=Mock(),scrape_upcoming_events=Mock(side_effect=ValueError('private detail')))
            with self.assertRaises(ValueError):collect(scraper,root)
            self.assertEqual(card.read_bytes(),b'prior verified generation')
            report=(root/'ufc_upcoming_status.json').read_text();self.assertEqual(json.loads(report)['state'],'failed');self.assertNotIn('private detail',report)
    def test_initialization_failure_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            scraper=SimpleNamespace(init_browser=Mock(side_effect=RuntimeError()),close_browser=Mock(),scrape_upcoming_events=Mock())
            with self.assertRaises(RuntimeError):collect(scraper,d)
            scraper.close_browser.assert_called_once();scraper.scrape_upcoming_events.assert_not_called()
