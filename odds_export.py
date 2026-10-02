"""Validated per-book odds snapshots; no network access on import."""
import csv
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ['event','fighter_a','fighter_b','odds_a','odds_b','best_odds_a','best_odds_b','num_books']

class OddsError(ValueError):
    pass

def stamp(value):
    if not isinstance(value, str):
        raise OddsError('Missing timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        raise OddsError('Invalid timestamp') from None

def name(value):
    if not isinstance(value, str) or not value.strip():
        raise OddsError('Missing identity')
    return value.strip()

def price(value):
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) < 100:
        raise OddsError('Invalid American price')
    return value

def decimal(value):
    return 1 + (value / 100 if value > 0 else 100 / abs(value))

def normalize(payload, fetched_at):
    fetched_at = stamp(fetched_at)
    if not isinstance(payload, list):
        raise OddsError('Expected event list')
    quotes, legacy, skipped = [], [], []
    seen_events = set()
    for event in payload:
        if not isinstance(event, dict):
            raise OddsError('Invalid event')
        event_id = name(event.get('id'))
        if event_id in seen_events or event.get('sport_key') != 'mma_mixed_martial_arts':
            raise OddsError('Duplicate event or wrong sport')
        seen_events.add(event_id)
        a, b = name(event.get('home_team')), name(event.get('away_team'))
        if a.casefold() == b.casefold():
            raise OddsError('Duplicate participants')
        start = stamp(event.get('commence_time'))
        books = event.get('bookmakers')
        if not isinstance(books, list):
            raise OddsError('Missing bookmakers')
        event_quotes, seen_books = [], set()
        for book in books:
            if not isinstance(book, dict):
                raise OddsError('Invalid bookmaker')
            key, title = name(book.get('key')), name(book.get('title'))
            if key in seen_books:
                raise OddsError('Duplicate bookmaker')
            seen_books.add(key)
            updated = stamp(book.get('last_update'))
            markets = book.get('markets')
            if not isinstance(markets, list):
                raise OddsError('Missing markets')
            h2h = [m for m in markets if isinstance(m, dict) and m.get('key') == 'h2h']
            if len(h2h) > 1:
                raise OddsError('Duplicate moneyline market')
            if not h2h:
                continue
            market = h2h[0]
            market_updated = stamp(market['last_update']) if 'last_update' in market else None
            if datetime.fromisoformat(updated) > datetime.fromisoformat(fetched_at) or (market_updated and datetime.fromisoformat(market_updated) > datetime.fromisoformat(fetched_at)):
                raise OddsError('Quote timestamp after fetch')
            outcomes = market.get('outcomes')
            if not isinstance(outcomes, list):
                raise OddsError('Missing outcomes')
            values = {}
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    raise OddsError('Invalid outcome')
                label = name(outcome.get('name'))
                if label in values:
                    raise OddsError('Duplicate outcome')
                values[label] = price(outcome.get('price'))
            if set(values) != {a, b}:
                skipped.append({'provider_event_id':event_id,'sportsbook_key':key,'reason':'incomplete_or_nonbinary_market'})
                continue
            quote = dict(provider_event_id=event_id,sport_key=event['sport_key'],commence_time=start,
                         fighter_a=a,fighter_b=b,sportsbook_key=key,sportsbook_title=title,
                         market='h2h',bookmaker_last_update=updated,market_last_update=market_updated,
                         fetched_at=fetched_at,odds_a=values[a],odds_b=values[b])
            quotes.append(quote)
            event_quotes.append(quote)
        if event_quotes:
            event_quotes.sort(key=lambda q:q['sportsbook_key'])
            first = event_quotes[0]
            best_a = max(event_quotes,key=lambda q:decimal(q['odds_a']))
            best_b = max(event_quotes,key=lambda q:decimal(q['odds_b']))
            legacy.append(dict(event=start,fighter_a=a,fighter_b=b,
                               odds_a=f"{first['odds_a']:+d}",odds_b=f"{first['odds_b']:+d}",
                               best_odds_a=f"{best_a['odds_a']:+d}",best_odds_b=f"{best_b['odds_b']:+d}",
                               num_books=str(len(event_quotes))))
    quotes.sort(key=lambda q:(q['provider_event_id'],q['sportsbook_key']))
    legacy.sort(key=lambda r:(r['event'],r['fighter_a'],r['fighter_b']))
    return dict(format='ufc-odds-quotes-v1',provider='the-odds-api',fetched_at=fetched_at,
                provider_event_count=len(payload),quotes=quotes,legacy_rows=legacy,skipped=skipped,
                identity_scope='Provider identities only; canonical UFC mapping required')

def encoded(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')

def atomic(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def publish(root, snapshot):
    root = Path(root)
    root.mkdir(parents=True,exist_ok=True)
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output,fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(snapshot['legacy_rows'])
    files = {'ufc_betting_odds.csv':output.getvalue().encode('utf-8'),
             'ufc_odds_quotes.json':encoded(snapshot)}
    status = dict(format='ufc-odds-status-v1',state='success',checked_at=snapshot['fetched_at'],
                  quote_count=len(snapshot['quotes']),event_count=snapshot['provider_event_count'],
                  files={k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
    files['ufc_odds_status.json'] = encoded(status)
    old = {k:(root/k).read_bytes() if (root/k).exists() else None for k in files}
    try:
        for filename,data in files.items():
            atomic(root/filename,data)
    except Exception:
        for filename,data in old.items():
            if data is None:
                (root/filename).unlink(missing_ok=True)
            else:
                atomic(root/filename,data)
        raise
    return status

def update(session, api_key, root='.', now=None):
    """Failure status invalidates freshness; previous successful data is preserved."""
    checked = stamp(now or datetime.now(timezone.utc).isoformat())
    try:
        if not api_key:
            raise OddsError('Missing provider key')
        response = session.get('https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds',
                               params=dict(regions='us',markets='h2h',oddsFormat='american',apiKey=api_key),timeout=15)
        response.raise_for_status()
        payload = response.json()
        fetched = now or datetime.now(timezone.utc).isoformat()
        snapshot = normalize(payload,fetched)
        return publish(root,snapshot)
    except Exception:
        # Never expose exception text or request URLs containing credentials.
        root = Path(root)
        root.mkdir(parents=True,exist_ok=True)
        status = dict(format='ufc-odds-status-v1',state='failed',checked_at=checked,
                      error='Odds update failed; prior successful prices are not fresh')
        atomic(root/'ufc_odds_status.json',encoded(status))
        return status
