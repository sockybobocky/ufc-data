import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from odds_budget import collect_daily, MONTHLY_LIMIT, RESERVE, LEDGER
from test_odds_export import fixture, NOW, Response

class Session:
 def __init__(self,remaining=400,missing=False,fail=False):self.calls=[];self.remaining=remaining;self.missing=missing;self.fail=fail
 def get(self,url,**kwargs):
  self.calls.append((url,kwargs))
  if self.fail:raise RuntimeError('secret-url-must-not-leak')
  response=Response(fixture())
  response.headers={} if self.missing else {'x-requests-remaining':str(self.remaining),'x-requests-used':'100','x-requests-last':'1' if url.endswith('/odds') else '0'}
  if url.endswith('/odds'):self.remaining-=1;response.headers['x-requests-remaining']=str(self.remaining)
  return response

class BudgetTests(unittest.TestCase):
 def test_activation_adopts_existing_success_without_spending_again_today(self):
  from odds_export import update
  with tempfile.TemporaryDirectory() as folder:
   update(Session(),'fake-key',folder,NOW)
   session=Session()
   self.assertEqual(collect_daily(session,'fake-key',folder,NOW)['state'],'success')
   self.assertEqual(session.calls,[])
   ledger=json.loads((Path(folder)/LEDGER).read_text())
   self.assertEqual(ledger['monthly_requests'],1)
 def test_reopening_and_manual_repeats_do_not_spend_more_credits_or_retimestamp(self):
  with tempfile.TemporaryDirectory() as folder:
   session=Session();first=collect_daily(session,'fake-key',folder,NOW)
   self.assertEqual(first['state'],'success');self.assertEqual(len(session.calls),2)
   raw=(Path(folder)/'ufc_odds_quotes.json').read_bytes()
   repeated=collect_daily(session,'fake-key',folder,(datetime.fromisoformat(NOW.replace('Z','+00:00'))+timedelta(hours=18)).isoformat())
   self.assertEqual(first['checked_at'],repeated['checked_at']);self.assertEqual(len(session.calls),2)
   self.assertEqual(raw,(Path(folder)/'ufc_odds_quotes.json').read_bytes())
   self.assertEqual(first['usage']['remaining'],399);self.assertEqual(first['monthly_collector_requests'],1)
 def test_next_day_can_fetch_again(self):
  with tempfile.TemporaryDirectory() as folder:
   session=Session();collect_daily(session,'fake-key',folder,NOW)
   next_day=(datetime.fromisoformat(NOW.replace('Z','+00:00'))+timedelta(days=1)).isoformat()
   self.assertEqual(collect_daily(session,'fake-key',folder,next_day)['monthly_collector_requests'],2);self.assertEqual(len(session.calls),4)
 def test_low_unknown_or_invalid_quota_never_requests_paid_odds(self):
  for session in (Session(RESERVE),Session(0),Session(missing=True),Session(-1)):
   with tempfile.TemporaryDirectory() as folder:
    self.assertEqual(collect_daily(session,'fake-key',folder,NOW)['state'],'failed')
    self.assertEqual(len(session.calls),1);self.assertTrue(session.calls[0][0].endswith('/sports'))
 def test_monthly_cap_and_corrupt_ledger_fail_closed_without_network(self):
  for raw in (json.dumps({'month':'2026-10','monthly_requests':MONTHLY_LIMIT}),'{broken',json.dumps({'monthly_requests':True})):
   with tempfile.TemporaryDirectory() as folder:
    (Path(folder)/LEDGER).write_text(raw);session=Session()
    self.assertEqual(collect_daily(session,'fake-key',folder,NOW)['state'],'failed');self.assertEqual(session.calls,[])
 def test_month_boundary_resets_local_cap_but_still_checks_shared_provider_quota(self):
  with tempfile.TemporaryDirectory() as folder:
   (Path(folder)/LEDGER).write_text(json.dumps({'month':'2026-09','monthly_requests':MONTHLY_LIMIT}))
   self.assertEqual(collect_daily(Session(),'fake-key',folder,NOW)['state'],'success')
 def test_failure_has_no_secret_details_or_automatic_retry(self):
  with tempfile.TemporaryDirectory() as folder:
   session=Session(fail=True);result=collect_daily(session,'fake-key',folder,NOW)
   self.assertNotIn('secret-url',json.dumps(result));self.assertNotIn('fake-key',json.dumps(result))
   collect_daily(session,'fake-key',folder,NOW);self.assertEqual(len(session.calls),1)

if __name__=='__main__':unittest.main()
