"""Upcoming cards only: history/model-training failures cannot block publication."""
import csv,io,json,hashlib,os,tempfile
from datetime import datetime,timezone
from pathlib import Path
from ufcstats_parser import ParseError,UPCOMING_FIELDS

def collect(scraper,root='.'):
    root=Path(root);status=root/'ufc_upcoming_status.json'
    checked=datetime.now(timezone.utc).isoformat()
    try:
        scraper.init_browser()
        rows=scraper.scrape_upcoming_events()
        if not rows or len({row['fight_url'] for row in rows})!=len(rows):raise ParseError('Empty or duplicated upcoming generation')
        output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=UPCOMING_FIELDS);writer.writeheader();writer.writerows(rows)
        data=output.getvalue().encode('utf-8')
        report={'format':'ufc-upcoming-status-v1','state':'success','checked_at':checked,'bout_count':len(rows),'sha256':hashlib.sha256(data).hexdigest(),'round_schedule':'Not supplied by event listing; separate source verification required'}
        atomic(root/'ufc_upcoming_events.csv',data)
        atomic(status,(json.dumps(report,indent=2)+'\n').encode())
        return report
    except Exception as exc:
        report={'format':'ufc-upcoming-status-v1','state':'failed','checked_at':checked,'error_type':type(exc).__name__,'prior_card_retained':True}
        atomic(status,(json.dumps(report,indent=2)+'\n').encode())
        raise
    finally:
        scraper.close_browser()

def atomic(path,data):
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

if __name__=='__main__':
    import scrape_ufc_data as scraper
    # Prevent the legacy collector from writing before the validated generation is ready.
    scraper.write_csv=lambda *args,**kwargs:None
    collect(scraper)
