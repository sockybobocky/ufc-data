"""Read-only recent-event audit; never publishes data or advances scraper state."""
import csv,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
from bs4 import BeautifulSoup
import scrape_ufc_data as scraper
from ufcstats_parser import parse_detail,parse_stats
from repair_history import write_csv
from ufcstats_parser import RESULT_FIELDS,STAT_FIELDS

def main():
 out=Path('recent_audit');out.mkdir(exist_ok=True)
 with open('ufc_fight_results.csv',encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
 known={r['FIGHT_URL'] for r in rows if r.get('FIGHT_URL')}
 cutoff=max(datetime.strptime(r['DATE'],'%B %d, %Y').date() for r in rows if r.get('FIGHT_URL'))
 report={'checked_at':datetime.now(timezone.utc).isoformat(),'imported_cutoff':str(cutoff),'events':[],'issues':[],'pages':{},'database_writes':0,'published_csv_writes':0}
 fights=[];stats=[]
 def page(url,label):
  response=scraper.fetch(url)
  if response is None:raise RuntimeError('Page retrieval failed: '+url)
  data=response.text.encode();(out/(label+'.html')).write_bytes(data)
  report['pages'][label]={'url':url,'sha256':hashlib.sha256(data).hexdigest()}
  return BeautifulSoup(response.text,'html.parser'),response.text
 try:
  scraper.init_browser()
  soup,_=page('http://www.ufcstats.com/statistics/events/completed?page=all','completed')
  links={a['href']:a.get_text(strip=True) for a in soup.select('a[href*="event-details"]')}
  if not links:raise RuntimeError('No authoritative event links; challenge or source failure')
  for i,(url,name) in enumerate(list(links.items())[:16]):
   event,_=page(url,'event_'+str(i))
   dates=[x.get_text(' ',strip=True).split('Date:',1)[1].strip() for x in event.select('li.b-list__box-list-item') if 'Date:' in x.get_text()]
   if not dates:raise RuntimeError('Missing event date '+url)
   date=datetime.strptime(dates[0],'%B %d, %Y').date()
   item={'url':url,'name':name,'date':str(date)};report['events'].append(item)
   if date<=cutoff:continue
   if date>datetime.now(timezone.utc).date():item['status']='future excluded';continue
   fightlinks=list(dict.fromkeys(a['href'] for a in event.select('a[href*="fight-details"]')))
   item['fight_urls']=fightlinks
   if not fightlinks:report['issues'].append({'event':url,'reason':'No completed fight identities'});continue
   for j,furl in enumerate(fightlinks):
    if furl in known:continue
    try:
     _,html=page(furl,f'fight_{i}_{j}');fight=parse_detail(html,furl,name,dates[0]);rounds=parse_stats(html,furl,name,fight['FIGHTER_A'],fight['FIGHTER_B'])
     expected={(p,str(r)) for p in (fight['FIGHTER_A'],fight['FIGHTER_B']) for r in range(1,int(fight['ROUND'])+1)}
     present={(r['FIGHTER'],r['ROUND']) for r in rounds if r.get('KD') is not None}
     if not expected.issubset(present):raise ValueError('Incomplete explicit round coverage')
     fights.append(fight);stats.extend(rounds)
    except Exception as e:report['issues'].append({'fight_url':furl,'reason':str(e)})
 except Exception as e:report['issues'].append({'reason':str(e)})
 finally:
  scraper.close_browser()
  write_csv(out/'ufc_fight_results.csv',fights,RESULT_FIELDS);write_csv(out/'ufc_fight_stats.csv',stats,STAT_FIELDS)
  report.update({'new_validated_fights':len(fights),'new_round_records':len(stats),'complete':not report['issues']})
  (out/'audit.json').write_text(json.dumps(report,indent=2))
 print(json.dumps({k:report[k] for k in ('complete','new_validated_fights','new_round_records','issues')}))
 if report['issues']:raise SystemExit(1)
if __name__=='__main__':main()
