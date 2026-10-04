"""One daily US moneyline request; quota probe is free and contains no public key."""
import json
from datetime import datetime, timezone
from pathlib import Path
from odds_export import atomic, encoded, stamp, update

LEDGER = 'ufc_odds_usage.json'
MONTHLY_LIMIT = 32
RESERVE = 25

def quota(response):
    headers = getattr(response, 'headers', {})
    result = {}
    for field, header in [('remaining', 'x-requests-remaining'), ('used', 'x-requests-used'), ('last_cost', 'x-requests-last')]:
        value = headers.get(header)
        if value is not None:
            if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).isdigit():
                raise ValueError('Invalid provider quota')
            result[field] = int(value)
    if 'remaining' not in result:
        raise ValueError('Provider quota unavailable')
    return result

def collect_daily(session, key, root='.', now=None):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    checked = stamp(now or datetime.now(timezone.utc).isoformat())
    current = datetime.fromisoformat(checked)
    ledger_path = root / LEDGER
    try:
        ledger = json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {}
        if not ledger:
            # Adopt the last pre-budget successful fetch, rather than fetching again today.
            status_path = root / 'ufc_odds_status.json'
            if status_path.exists():
                previous = json.loads(status_path.read_text(encoding='utf-8'))
                if previous.get('state') == 'success':
                    prior = stamp(previous['checked_at'])
                    ledger = {'month': prior[:7], 'monthly_requests': 1, 'last_attempt_at': prior,
                              'monthly_limit': MONTHLY_LIMIT, 'reserve': RESERVE}
                    atomic(ledger_path, encoded(ledger))
        if not isinstance(ledger, dict): raise ValueError('Invalid usage ledger')
        attempts = ledger.get('monthly_requests', 0)
        if type(attempts) is not int or attempts < 0: raise ValueError('Invalid usage ledger')
        if ledger.get('month') != checked[:7]: attempts = 0
        last = ledger.get('last_attempt_at')
        if last:
            age = (current - datetime.fromisoformat(stamp(last))).total_seconds()
            if age < 0: raise ValueError('Usage ledger is in the future')
            if datetime.fromisoformat(stamp(last)).date() == current.date():
                previous = json.loads((root / 'ufc_odds_status.json').read_text(encoding='utf-8'))
                return {**previous, 'budget_message': 'Daily attempt already made; cached prices retain their original timestamps.'}
        if attempts >= MONTHLY_LIMIT: raise ValueError('Monthly collector cap reached')
        if not key: raise ValueError('Provider key unavailable')
        ledger.update(month=checked[:7], monthly_requests=attempts, last_attempt_at=checked,
                      monthly_limit=MONTHLY_LIMIT, reserve=RESERVE)
        atomic(ledger_path, encoded(ledger))  # Persist even failed attempts; no automatic paid retries.
        probe = session.get('https://api.the-odds-api.com/v4/sports', params={'apiKey': key}, timeout=15)
        probe.raise_for_status()
        usage = quota(probe)
        ledger['provider_quota'] = usage
        atomic(ledger_path, encoded(ledger))
        if usage['remaining'] <= RESERVE: raise ValueError('Provider quota reserve reached')
        ledger['monthly_requests'] += 1  # Reserve before network; interrupted requests still count.
        atomic(ledger_path, encoded(ledger))
        class RecordingSession:
            def get(self, url, **kwargs):
                response = session.get(url, **kwargs)
                try:
                    ledger['provider_quota'] = quota(response)
                    ledger['quota_checked_at'] = checked
                    atomic(ledger_path, encoded(ledger))
                except ValueError:
                    ledger['provider_quota'] = {'remaining': 0, 'unavailable': True}
                    atomic(ledger_path, encoded(ledger))
                return response
        result = update(RecordingSession(), key, root, now)
        result['usage'] = ledger['provider_quota']
        result['monthly_collector_requests'] = ledger['monthly_requests']
        result['monthly_collector_limit'] = MONTHLY_LIMIT
        atomic(root / 'ufc_odds_status.json', encoded(result))
        return result
    except Exception:
        result = dict(format='ufc-odds-status-v1', state='failed', checked_at=checked,
                      error='Daily odds update held: provider quota, usage budget, credentials or connection needs review. Prior prices were not refreshed.')
        atomic(root / 'ufc_odds_status.json', encoded(result))
        return result
