"""Record failure stages without changing scraper parsing or publication guards."""
import json
from datetime import datetime, timezone
from pathlib import Path

STAGES = {
    'init_browser': 'browser_startup',
    'scrape_fighter_records': 'fighter_records',
    'scrape_all_fighter_stats': 'full_fighter_statistics',
    'update_upcoming_fighter_stats': 'upcoming_fighter_statistics',
    'scrape_events_and_fights': 'historical_events_and_fights',
    'scrape_upcoming_events': 'upcoming_cards',
    'scrape_upcoming_profiles': 'upcoming_profiles',
    'fetch_betting_odds': 'odds',
    'close_browser': 'browser_cleanup',
}


def run(scraper, report_path=Path('scraper_run_diagnostics.json')):
    report = {'schema_version': 1, 'started_at': datetime.now(timezone.utc).isoformat(),
              'state': 'running', 'phase': 'main_initialization', 'first_failure': None,
              'scope': 'Stage diagnostics only; partial file writes are not ruled out.'}
    originals = {}

    def wrap(function, phase):
        def invoke(*args, **kwargs):
            report['phase'] = phase
            try:
                return function(*args, **kwargs)
            except BaseException as exc:
                if report['first_failure'] is None:
                    report['first_failure'] = {'phase': phase, 'exception_type': type(exc).__name__}
                raise
        return invoke

    try:
        for name, phase in STAGES.items():
            function = getattr(scraper, name, None)
            if callable(function):
                originals[name] = function
                setattr(scraper, name, wrap(function, phase))
        scraper.main()
        report['state'] = 'completed'
    except BaseException as exc:
        report['state'] = 'failed'
        report['propagated_exception_type'] = type(exc).__name__
        if report['first_failure'] is None:
            report['first_failure'] = {'phase': report['phase'], 'exception_type': type(exc).__name__}
        raise
    finally:
        for name, function in originals.items():
            setattr(scraper, name, function)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        try:
            Path(report_path).write_text(json.dumps(report, indent=2), encoding='utf-8')
        except Exception:
            # A diagnostics failure must not turn failure into success or hide its exception.
            print('Stage diagnostics could not be saved.')


if __name__ == '__main__':
    import scrape_ufc_data
    run(scrape_ufc_data)
