"""Run up to five checkpointed historical batches with isolated output files."""
import argparse
import json
from pathlib import Path
from collections import Counter
from backfill_history import run, atomic_json, select
from repair_history import read_csv, write_csv
from ufcstats_parser import RESULT_FIELDS, STAT_FIELDS

def run_batches(source, output, fetch, limit=100, offset=0, batches=1, resume=False):
    if not 1 <= batches <= 5 or not 1 <= limit <= 100 or offset < 0:
        raise ValueError('Invalid bounded batch range')
    output = Path(output)
    if output.exists() and not resume:
        raise ValueError('Output exists; resume or choose a new directory')
    if resume and not output.exists():
        raise ValueError('Resume output does not exist')
    output.mkdir(parents=True,exist_ok=True)
    selection = {'limit':limit,'offset':offset,'batches':batches}
    settings = output/'batch-selection.json'
    if settings.exists() and json.loads(settings.read_text()) != selection:
        raise ValueError('Batch selection changed; use a new output directory')
    atomic_json(settings,selection)
    reports,results,stats = [],[],[]
    source_rows = read_csv(source)
    for index in range(batches):
        position = offset + index*limit
        if not select(source_rows,limit,position):
            break
        directory = output/f'batch-{position:05d}'
        report = run(source,directory,fetch,limit=limit,offset=position,resume=directory.exists())
        reports.append(report)
        results.extend(read_csv(directory/'ufc_fight_results.csv'))
        stats.extend(read_csv(directory/'ufc_fight_stats.csv'))
        if report['failed']:
            break
    if not reports:
        raise ValueError('No fights in requested range')
    urls = [r['FIGHT_URL'] for r in results]
    if len(urls)!=len(set(urls)):
        raise ValueError('Batch selections overlap')
    write_csv(output/'ufc_fight_results.csv',results,RESULT_FIELDS)
    write_csv(output/'ufc_fight_stats.csv',stats,STAT_FIELDS)
    aggregate = {key:sum(r[key] for r in reports) for key in ('selected','fetched_this_run','repaired','quarantined','failed')}
    aggregate.update(offset=offset,next_offset=offset+aggregate['selected'],batches_completed=len(reports),
        issues=[issue for r in reports for issue in r['issues']],outcomes=dict(Counter(r['OUTCOME'] for r in results)))
    atomic_json(output/'repair-report.json',aggregate)
    return aggregate

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('ufc_fight_results.csv'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--batches',type=int,default=1)
    parser.add_argument('--resume',action='store_true')
    args = parser.parse_args()
    import scrape_ufc_data as scraper
    def fetch(url):
        response = scraper.fetch(url)
        if response is None:
            raise RuntimeError('Page retrieval failed')
        return response.text
    try:
        scraper.init_browser()
        report = run_batches(args.source,args.output,fetch,args.limit,args.offset,args.batches,args.resume)
    finally:
        scraper.close_browser()
    print(json.dumps(report,indent=2))
    if report['failed']:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
