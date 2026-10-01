import csv
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from ufcstats_parser import ParseError, parse_detail, parse_stats, round_format
from repair_history import repair_records

URL = 'http://ufcstats.com/fight-details/0000000000000004'
A = 'http://ufcstats.com/fighter-details/0000000000000001'
B = 'http://ufcstats.com/fighter-details/0000000000000002'

def fixture(status=('W','L'),method='KO/TKO',time_format='3 Rnd (5-5-5)',with_round=True):
    persons = ''.join(f'<div class="b-fight-details__person"><i class="b-fight-details__person-status">{s}</i><h3><a href="{u}">{name}</a></h3></div>' for s,u,name in zip(status,(A,B),('Red','Blue')))
    metadata = f'<p class="b-fight-details__text"><i>Method:</i><i>{method}</i> <i>Round:</i>1 <i>Time:</i>1:00 <i>Time format:</i>{time_format} <i>Referee:</i>Test</p>'
    def table(headers,values,per_round):
        header = '<tr>'+''.join(f'<th>{name}</th>' for name in ['Fighter']+headers)+'</tr>'
        marker = '<tr><th colspan="10">Round 1</th></tr>' if per_round else ''
        names = f'<td><p><a href="{A}">Red</a></p><p><a href="{B}">Blue</a></p></td>'
        data = '<tr>'+names+''.join(f'<td><p>{a}</p><p>{b}</p></td>' for a,b in values)+'</tr>'
        return '<table><thead>'+header+'</thead><tbody>'+marker+data+'</tbody></table>'
    main_headers = ['KD','Sig. str.','Sig. str. %','Total str.','Td','Td %','Sub. att','Rev.','Ctrl']
    main = [('1','0'),('4 of 8','2 of 6'),('50%','33%'),('5 of 9','3 of 7'),('0 of 0','0 of 1'),('---','0%'),('0','0'),('0','0'),('0:20','0:10')]
    sig_headers = ['Sig. str.','Sig. str. %','Head','Body','Leg','Distance','Clinch','Ground']
    sig = [('4 of 8','2 of 6'),('50%','33%'),('2 of 4','1 of 3'),('1 of 2','1 of 2'),('1 of 2','0 of 1'),('3 of 6','2 of 5'),('1 of 2','0 of 1'),('0 of 0','0 of 0')]
    tables = table(main_headers,main,False)+table(sig_headers,sig,False)
    if with_round:
        tables += table(main_headers,main,True)+table(sig_headers,sig,True)
    return '<html>'+persons+'<a href="http://ufcstats.com/event-details/0000000000000005">Test event</a><i class="b-fight-details__fight-title">Lightweight Bout</i>'+metadata+tables+'</html>'

class ParserTests(unittest.TestCase):
    def test_detail(self):
        result = parse_detail(fixture(),URL,'Test','September 01, 2026')
        self.assertEqual(result['METHOD'],'KO/TKO')
        self.assertEqual(result['SCHEDULED_ROUNDS'],'3')
        self.assertEqual(result['ROUND_LENGTH_SECONDS'],'300')
        self.assertEqual(result['FIGHTER_A_URL'],A)
        self.assertEqual(result['WINNER'],'Red')
    def test_reversed_winner(self):
        self.assertEqual(parse_detail(fixture(('L','W')),URL)['WINNER'],'Blue')
    def test_draw_and_no_contest_distinct(self):
        self.assertEqual(parse_detail(fixture(('D','D')),URL)['OUTCOME'],'D/D')
        self.assertEqual(parse_detail(fixture(('NC','NC'),method='Overturned'),URL)['OUTCOME'],'NC/NC')
    def test_single_round_preserved(self):
        rows = parse_stats(fixture(),URL,'Test','Red','Blue')
        self.assertEqual(len(rows),4)
        self.assertEqual({row['ROUND'] for row in rows},{'1','Total'})
    def test_targeting_mapping(self):
        row = next(r for r in parse_stats(fixture(),URL,'Test','Red','Blue') if r['FIGHTER']=='Red' and r['ROUND']=='1')
        self.assertEqual(row['HEAD'],'2 of 4')
        self.assertEqual(row['BODY'],'1 of 2')
        self.assertEqual(row['GROUND'],'0 of 0')
        self.assertEqual(row['SIG.STR. %'],'50%')
    def test_duplicate_td_percent_heading(self):
        html = fixture().replace('<th>Td</th>','<th>Td %</th>')
        self.assertEqual(parse_stats(html,URL,'Test','Red','Blue')[0]['TD'],'0 of 0')
    def test_challenge_rejected(self):
        with self.assertRaises(ParseError): parse_detail('<html>Checking your browser</html>',URL)
    def test_missing_field_rejected(self):
        with self.assertRaises(ParseError): parse_detail(fixture().replace('Method:','Unknown:'),URL)
    def test_historical_format_preserved(self):
        result = parse_detail(fixture(time_format='1 Rnd + OT (12-3)'),URL)
        self.assertEqual(result['TIME_FORMAT'],'1 Rnd + OT (12-3)')
        self.assertEqual(result['SCHEDULED_ROUNDS'],'')
    def test_bad_stat_rejected(self):
        with self.assertRaises(ParseError): parse_stats(fixture().replace('1 of 2','50%'),URL,'Test','Red','Blue')
    def test_format(self):
        self.assertEqual(round_format('5 Rnd (5-5-5-5-5)'),('5','300'))
        self.assertEqual(round_format('1 Rnd (12)'),('',''))
    def test_repair_sample(self):
        source = [{'FIGHT_URL':URL,'EVENT':'Test','DATE':'September 01, 2026'}]
        results,stats,errors = repair_records(source,lambda url:fixture(),5)
        self.assertEqual(len(results),1)
        self.assertEqual(len(stats),4)
        self.assertEqual(errors,[])
    def test_missing_round_sample_fails(self):
        source = [{'FIGHT_URL':URL,'EVENT':'Test','DATE':'September 01, 2026'}]
        results,stats,errors = repair_records(source,lambda url:fixture(with_round=False),5)
        self.assertEqual(results,[])
        self.assertEqual(len(errors),1)

class ScraperIntegrationTests(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location('scraper_test',Path(__file__).parent/'scrape_ufc_data.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',{'requests':MagicMock()}):
            spec.loader.exec_module(module)
        return module
    def run_scrape(self,bad=False,poisoned=False):
        scraper = self.load()
        event_url = 'http://ufcstats.com/event-details/0000000000000005'
        pages = {'http://www.ufcstats.com/statistics/events/completed?page=all':f'<a href="{event_url}">Test</a>',
                 event_url:f'<li class="b-list__box-list-item">Date: September 01, 2026</li><a href="{URL}">Fight</a>',
                 URL:'<html>Checking your browser</html>' if bad else fixture()}
        scraper.fetch = lambda url:type('Response',(),{'text':pages[url]})()
        state = {'scraped_events':[]}
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp, patch.object(scraper.time,'sleep'):
            try:
                os.chdir(temp)
                originals = {'ufc_fight_results.csv':'original-results','ufc_fight_stats.csv':'original-stats'}
                if bad:
                    for name,data in originals.items(): Path(name).write_text(data)
                    with self.assertRaises(RuntimeError): scraper.scrape_events_and_fights(state,full=True)
                    for name,data in originals.items(): self.assertEqual(Path(name).read_text(),data)
                    self.assertEqual(state['scraped_events'],[])
                    self.assertEqual(len(json.loads(Path('scraper_repair_errors.json').read_text())),1)
                else:
                    if poisoned:
                        state['scraped_events']=[event_url]
                        with Path('ufc_fight_results.csv').open('w',newline='') as handle:
                            writer=csv.DictWriter(handle,['EVENT','BOUT','FIGHT_URL','OUTCOME','METHOD','ROUND','TIME']);writer.writeheader();writer.writerow({'EVENT':'Test','BOUT':'Red vs. Blue'})
                    scraper.scrape_events_and_fights(state)
                    with Path('ufc_fight_results.csv').open() as handle: results = list(csv.DictReader(handle))
                    self.assertEqual(results[0]['METHOD'],'KO/TKO')
                    self.assertEqual(results[0]['SCHEDULED_ROUNDS'],'3')
                    scraper.scrape_events_and_fights(state)
                    with Path('ufc_fight_results.csv').open() as handle: self.assertEqual(len(list(csv.DictReader(handle))),1)
            finally:
                os.chdir(old_cwd)
    def test_cached_incomplete_event_retried(self): self.run_scrape(poisoned=True)
    def test_batch_and_repeat(self): self.run_scrape()
    def test_failed_batch_preserves_originals(self): self.run_scrape(True)

if __name__ == '__main__': unittest.main()
