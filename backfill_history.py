"""Checkpointed, separate-output historical repair. Never modifies source CSVs."""
import argparse
import hashlib
import json
from pathlib import Path
from repair_history import read_csv, write_csv
from ufcstats_parser import RESULT_FIELDS, STAT_FIELDS, parse_detail, parse_stats

def digest(data):
    return hashlib.sha256(data).hexdigest()

def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)

def select(rows, limit):
    unique = {row['FIGHT_URL']: row for row in rows if row.get('FIGHT_URL')}
    rows = list(unique.values())
    special = [r for r in rows if r.get('OUTCOME') == 'D/D'][:8]
    old = [r for r in rows if r.get('TIME','').split(':')[0].isdigit() and int(r['TIME'].split(':')[0]) > 5][:4]
    chosen = dict((r['FIGHT_URL'],r) for r in rows[:5]+special+old+rows)
    return list(chosen.values())[:limit]

def run(source, output, fetch, limit=25, resume=False, retry_failed=False):
    source, output = Path(source), Path(output)
    selected = select(read_csv(source), limit)
    manifest = {'source_sha256':digest(source.read_bytes()),
                'parser_sha256':digest(Path(__file__).with_name('ufcstats_parser.py').read_bytes()),
                'backfill_sha256':digest(Path(__file__).read_bytes()),
                'urls':[r['FIGHT_URL'] for r in selected]}
    if output.exists():
        if not resume:
            raise ValueError('Output exists; use --resume or choose a new directory')
        if json.loads((output/'manifest.json').read_text()) != manifest:
            raise ValueError('Source, selection, or parser changed; use a new output directory')
    else:
        if resume:
            raise ValueError('Cannot resume a missing output directory')
        output.mkdir(parents=True)
        atomic_json(output/'manifest.json',manifest)
    checkpoints = output/'checkpoints'
    checkpoints.mkdir(exist_ok=True)
    records = []
    fetched = 0
    for source_row in selected:
        url = source_row['FIGHT_URL']
        path = checkpoints/(digest(url.encode())+'.json')
        record = json.loads(path.read_text()) if path.exists() else None
        if record and record.get('url') != url:
            raise ValueError('Checkpoint identity mismatch')
        if record is None or (retry_failed and record['status']=='failed'):
            record = {'url':url,'status':'failed'}
            try:
                html = fetch(url)
                fetched += 1
                raw = path.with_suffix('.html')
                raw.write_text(html,encoding='utf-8')
                record['html_sha256'] = digest(html.encode())
                fight = parse_detail(html,url,source_row.get('EVENT',''),source_row.get('DATE',''))
                record['fight'] = fight
                if not fight['SCHEDULED_ROUNDS']:
                    record.update(status='quarantined',reason='Unsupported historical time format: '+fight['TIME_FORMAT'])
                else:
                    stats = parse_stats(html,url,fight['EVENT'],fight['FIGHTER_A'],fight['FIGHTER_B'])
                    expected = {(name,str(r)) for name in (fight['FIGHTER_A'],fight['FIGHTER_B']) for r in range(1,int(fight['ROUND'])+1)}
                    present = {(r['FIGHTER'],r['ROUND']) for r in stats if r.get('KD') is not None}
                    if not expected.issubset(present):
                        raise ValueError('Explicit main round coverage incomplete')
                    record.update(status='repaired',stats=stats)
            except (ValueError, RuntimeError) as exc:
                record.update(status='failed',reason=str(exc))
            atomic_json(path,record)
        records.append(record)
    repaired = [r for r in records if r['status']=='repaired']
    write_csv(output/'ufc_fight_results.csv',[r['fight'] for r in repaired],RESULT_FIELDS)
    write_csv(output/'ufc_fight_stats.csv',[s for r in repaired for s in r['stats']],STAT_FIELDS)
    report = {'selected':len(records),'fetched_this_run':fetched,
              **{status:sum(r['status']==status for r in records) for status in ('repaired','quarantined','failed')},
              'issues':[{'url':r['url'],'status':r['status'],'reason':r['reason']} for r in records if r['status']!='repaired'],
              'outcomes':{o:sum(r['fight']['OUTCOME']==o for r in repaired) for o in sorted({r['fight']['OUTCOME'] for r in repaired})}}
    atomic_json(output/'repair-report.json',report)
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('ufc_fight_results.csv'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=25)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--retry-failed',action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('Limit must be between 1 and 100')
    import scrape_ufc_data as scraper
    def fetch(url):
        response = scraper.fetch(url)
        if response is None:
            raise RuntimeError('Page retrieval failed')
        return response.text
    try:
        scraper.init_browser()
        report = run(args.source,args.output,fetch,args.limit,args.resume,args.retry_failed)
    finally:
        scraper.close_browser()
    print(json.dumps(report,indent=2))
    if report['failed']:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
