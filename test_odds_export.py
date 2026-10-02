import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import odds_export as export

NOW='2026-10-02T04:00:00Z'
def fixture():
    return [dict(id='event-1',sport_key='mma_mixed_martial_arts',commence_time='2026-10-04T04:30:00Z',home_team='Red',away_team='Blue',bookmakers=[dict(key='book-a',title='Book A',last_update='2026-10-02T03:00:00Z',markets=[dict(key='h2h',outcomes=[dict(name='Blue',price=150),dict(name='Red',price=-180)])])])]

class Response:
    def __init__(self,payload): self.payload=payload
    def raise_for_status(self): pass
    def json(self): return self.payload
class Session:
    def __init__(self,payload): self.payload=payload; self.calls=[]
    def get(self,url,**kwargs): self.calls.append((url,kwargs)); return Response(self.payload)

class OddsTests(unittest.TestCase):
    def test_scraper_wrapper_uses_exporter(self):
        import ast
        import contextlib
        import io
        source=(Path(__file__).parent/'scrape_ufc_data.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='fetch_betting_odds')
        code=compile(ast.Module(body=[function],type_ignores=[]),'<isolated wrapper>','exec')
        namespace={'API_SESSION':object(),'ODDS_API_KEY':'fake-key'}
        exec(code,namespace)
        with patch.object(export,'update',return_value={'state':'failed'}) as call, contextlib.redirect_stdout(io.StringIO()) as captured:
            status=namespace['fetch_betting_odds']()
        call.assert_called_once_with(namespace['API_SESSION'],'fake-key')
        self.assertEqual(status['state'],'failed')
        self.assertNotIn('fake-key',captured.getvalue())
    def test_swapped_outcomes_and_provenance(self):
        q=export.normalize(fixture(),NOW)['quotes'][0]
        self.assertEqual((q['odds_a'],q['odds_b']),(-180,150))
        self.assertEqual(q['sportsbook_key'],'book-a')
        self.assertIsNone(q['market_last_update'])
        self.assertNotEqual(q['commence_time'],q['bookmaker_last_update'])
    def test_incomplete_book_never_combines_prices(self):
        p=fixture(); first=p[0]['bookmakers'][0]
        second=copy.deepcopy(first); second['key']='book-b'
        first['markets'][0]['outcomes']=[dict(name='Red',price=-110)]
        second['markets'][0]['outcomes']=[dict(name='Blue',price=140)]
        p[0]['bookmakers'].append(second)
        s=export.normalize(p,NOW)
        self.assertEqual(s['quotes'],[]); self.assertEqual(s['legacy_rows'],[])
        self.assertEqual(len(s['skipped']),2)
    def test_legacy_same_book_and_best_price_origin_retained(self):
        p=fixture(); second=copy.deepcopy(p[0]['bookmakers'][0]); second['key']='book-b'
        second['markets'][0]['outcomes']=[dict(name='Red',price=-160),dict(name='Blue',price=130)]
        p[0]['bookmakers'].append(second)
        s=export.normalize(p,NOW); row=s['legacy_rows'][0]
        self.assertEqual((row['odds_a'],row['odds_b']),('-180','+150'))
        self.assertEqual((row['best_odds_a'],row['best_odds_b']),('-160','+150'))
        self.assertEqual(len(s['quotes']),2)
    def test_duplicate_names_books_events(self):
        p=fixture(); p[0]['bookmakers'][0]['markets'][0]['outcomes'][1]['name']='Blue'
        with self.assertRaises(export.OddsError): export.normalize(p,NOW)
        p=fixture(); p[0]['bookmakers']*=2
        with self.assertRaises(export.OddsError): export.normalize(p,NOW)
        with self.assertRaises(export.OddsError): export.normalize(fixture()*2,NOW)
    def test_invalid_price_types(self):
        for value in [True,0,90,150.5,'+150','150junk']:
            with self.subTest(value=value):
                p=fixture(); p[0]['bookmakers'][0]['markets'][0]['outcomes'][0]['price']=value
                with self.assertRaises(export.OddsError): export.normalize(p,NOW)
    def test_timestamps(self):
        for value in [None,'bad','2026-10-02T03:00:00','2026-10-02T05:00:00Z']:
            p=fixture(); p[0]['bookmakers'][0]['last_update']=value
            with self.assertRaises(export.OddsError): export.normalize(p,NOW)
        p=fixture(); p[0]['bookmakers'][0]['last_update']='2026-10-02T04:00:00.1Z'
        with self.assertRaises(export.OddsError): export.normalize(p,NOW)
    def test_repeat_hashes_and_status(self):
        with tempfile.TemporaryDirectory() as folder:
            a=export.update(Session(fixture()),'fake-key',folder,NOW)
            b=export.update(Session(fixture()),'fake-key',folder,NOW)
            self.assertEqual(a,b)
            for filename,digest in a['files'].items():
                self.assertEqual(hashlib.sha256((Path(folder)/filename).read_bytes()).hexdigest(),digest)
    def test_transport_and_json_failure_preserve_files(self):
        with tempfile.TemporaryDirectory() as folder:
            export.update(Session(fixture()),'fake-key',folder,NOW)
            root=Path(folder); before={n:(root/n).read_bytes() for n in ['ufc_odds_quotes.json','ufc_betting_odds.csv']}
            for failure in [RuntimeError('apiKey=secret'),ValueError('JSON')]:
                with patch.object(Session,'get',side_effect=failure):
                    status=export.update(Session(None),'secret',folder,NOW)
                self.assertEqual(status['state'],'failed')
                self.assertNotIn('secret',(root/'ufc_odds_status.json').read_text())
                self.assertEqual(before,{n:(root/n).read_bytes() for n in before})
    def test_invalid_response_preserves_files(self):
        with tempfile.TemporaryDirectory() as folder:
            export.update(Session(fixture()),'key',folder,NOW)
            original=(Path(folder)/'ufc_odds_quotes.json').read_bytes()
            self.assertEqual(export.update(Session({'error':'quota'}),'key',folder,NOW)['state'],'failed')
            self.assertEqual(original,(Path(folder)/'ufc_odds_quotes.json').read_bytes())
    def test_successful_empty_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            export.update(Session(fixture()),'key',folder,NOW)
            status=export.update(Session([]),'key',folder,NOW)
            self.assertEqual((status['state'],status['event_count'],status['quote_count']),('success',0,0))
            self.assertEqual(json.loads((Path(folder)/'ufc_odds_quotes.json').read_text())['quotes'],[])
    def test_atomic_write_failure_restores_data(self):
        with tempfile.TemporaryDirectory() as folder:
            export.update(Session(fixture()),'key',folder,NOW)
            root=Path(folder); before={n:(root/n).read_bytes() for n in ['ufc_odds_quotes.json','ufc_betting_odds.csv']}
            original=export.atomic; calls=0
            def fail_once(path,data):
                nonlocal calls
                calls+=1
                if calls==2: raise OSError('disk failure')
                original(path,data)
            with patch.object(export,'atomic',side_effect=fail_once):
                self.assertEqual(export.update(Session([]),'key',folder,NOW)['state'],'failed')
            self.assertEqual(before,{n:(root/n).read_bytes() for n in before})

if __name__=='__main__': unittest.main()
