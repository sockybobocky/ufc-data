import json,unittest
from pathlib import Path
from html import escape
from ufcstats_parser import parse_upcoming, ParseError, UPCOMING_FIELDS
ROOT=Path(__file__).resolve().parent
CARDS=json.loads((ROOT/'tests/fixtures/upcoming-five-cards.json').read_text())
def fixture(card):
    metadata=''.join('<li class="b-list__box-list-item">'+escape(x)+'</li>' for x in card['metadata'])
    rows=[]
    for bout in card['bouts']:
        cells=['<td>'+escape(x)+'</td>' for x in bout['cells']]
        cells[1]='<td>'+''.join('<a href="'+escape(p['url'])+'">'+escape(p['name'])+'</a>' for p in bout['participants'])+'</td>'
        rows.append('<tr class="b-fight-details__table-row" data-link="'+escape(bout['detail'])+'">'+''.join(cells)+'</tr>')
    return metadata+'<table>'+''.join(rows)+'</table>'
class UpcomingParser(unittest.TestCase):
    def parse(self,html=None):
        c=CARDS[0]
        return parse_upcoming(html or fixture(c),c['event_url'],c['event_name'],c['checked_at'])
    def test_audited_five_cards(self):
        allrows=[]
        for c in CARDS:
            rows=parse_upcoming(fixture(c),c['event_url'],c['event_name'],c['checked_at'])
            self.assertEqual(len(rows),len(c['bouts']));allrows.extend(rows)
            for r,b in zip(rows,c['bouts']):
                self.assertEqual(r['fight_url'].split('/')[-1],b['detail'].split('/')[-1])
                self.assertEqual(r['weight_class'],b['cells'][6])
                self.assertEqual(set(r),set(UPCOMING_FIELDS))
                self.assertNotIn('scheduled_rounds',r)
        self.assertEqual(len(allrows),59)
    def test_browser_check_rejected(self):
        with self.assertRaises(ParseError):self.parse('<html>Check your browser</html>')
    def test_identity_spoof_rejected(self):
        with self.assertRaises(ParseError):self.parse(fixture(CARDS[0]).replace('ufcstats.com/fighter-details','ufcstats.com.evil/fighter-details'))
    def test_missing_fight_link_rejected(self):
        with self.assertRaises(ParseError):self.parse(fixture(CARDS[0]).replace('data-link=', 'unused='))
    def test_duplicate_rejected(self):
        html=fixture(CARDS[0]);first=html[html.index('<tr '):html.index('</tr>')+5]
        with self.assertRaises(ParseError):self.parse(html.replace('</table>',first+'</table>'))
    def test_missing_date_rejected(self):
        with self.assertRaises(ParseError):self.parse(fixture(CARDS[0]).replace('Date:', 'Unknown:').replace('DATE:', 'UNKNOWN:'))
    def test_naive_timestamp_rejected(self):
        c=CARDS[0]
        with self.assertRaises(ParseError):parse_upcoming(fixture(c),c['event_url'],c['event_name'],'2026-10-01T12:00:00')


class UpcomingPublication(unittest.TestCase):
    def run_scrape(self,responses):
        import ast
        from unittest.mock import Mock
        from bs4 import BeautifulSoup
        from datetime import datetime,timezone
        import types
        tree=ast.parse((ROOT/'scrape_ufc_data.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='scrape_upcoming_events')
        fetch=Mock(side_effect=[types.SimpleNamespace(text=x) if x is not None else None for x in responses])
        write=Mock()
        from ufcstats_parser import canonical_url
        namespace=dict(fetch=fetch,write_csv=write,BeautifulSoup=BeautifulSoup,datetime=datetime,timezone=timezone,
                       parse_upcoming=parse_upcoming,canonical_url=canonical_url,UPCOMING_FIELDS=UPCOMING_FIELDS,
                       ParseError=ParseError,time=types.SimpleNamespace(sleep=lambda n:None))
        exec(compile(ast.Module(body=[function],type_ignores=[]),'scraper-fixture','exec'),namespace)
        return namespace['scrape_upcoming_events'],write
    def index(self):
        return ''.join('<a href="'+c['event_url']+'">'+c['event_name']+'</a>' for c in CARDS)
    def test_partial_card_failure_does_not_publish(self):
        run,write=self.run_scrape([self.index(),fixture(CARDS[0]),None])
        with self.assertRaises(ParseError):run()
        write.assert_not_called()
    def test_complete_cards_published_once(self):
        run,write=self.run_scrape([self.index()]+[fixture(c) for c in CARDS])
        rows=run();self.assertEqual(len(rows),59);write.assert_called_once()
    def test_empty_index_does_not_publish(self):
        run,write=self.run_scrape(['<html>Check your browser</html>'])
        with self.assertRaises(ParseError):run()
        write.assert_not_called()

if __name__=='__main__':unittest.main()
