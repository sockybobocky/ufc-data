"""Bounded repair of existing fights; originals remain untouched by default.

python repair_history.py --limit 5 --output repaired_sample
Run in the data repository environment. Requires its existing browser setup.
"""
import argparse
import csv
import json
from pathlib import Path
from ufcstats_parser import ParseError, RESULT_FIELDS, STAT_FIELDS, parse_detail, parse_stats

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as handle:
        return list(csv.DictReader(handle))

def write_csv(path,rows,fields):
    with Path(path).open('w',encoding='utf-8',newline='') as handle:
        writer = csv.DictWriter(handle,fields,extrasaction='raise')
        writer.writeheader()
        writer.writerows({key:row.get(key,'') for key in fields} for row in rows)

def repair_records(results,fetch_html,limit):
    repaired,stats,issues = [],[],[]
    # Only bounded existing URLs are fetched; never guesses a missing identity.
    candidates = [row for row in results if row.get('FIGHT_URL')][:limit]
    for source in candidates:
        url = source['FIGHT_URL']
        try:
            html = fetch_html(url)
            fight = parse_detail(html,url,source.get('EVENT',''),source.get('DATE',''))
            rounds = parse_stats(html,url,fight['EVENT'],fight['FIGHTER_A'],fight['FIGHTER_B'])
            finish = int(fight['ROUND'])
            expected = {(name,str(rnd)) for name in (fight['FIGHTER_A'],fight['FIGHTER_B']) for rnd in range(1,finish+1)}
            present = {(row['FIGHTER'],row['ROUND']) for row in rounds if row.get('KD') is not None}
            if not expected.issubset(present):
                raise ParseError('Explicit main round coverage incomplete')
            if not fight['SCHEDULED_ROUNDS']:
                raise ParseError('Historical time format needs a separate import policy: '+fight['TIME_FORMAT'])
            repaired.append(fight)
            stats.extend(rounds)
        except (ParseError,ValueError,RuntimeError) as exc:
            issues.append({'fight_url':url,'reason':str(exc)})
    return repaired,stats,issues

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=5)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('limit must be between 1 and 100 for staged verification')
    if args.output.exists():
        parser.error('output directory already exists; choose a new sample directory')
    import scrape_ufc_data as scraper
    def fetch_html(url):
        response = scraper.fetch(url)
        if response is None:
            raise RuntimeError('Page retrieval failed')
        return response.text
    try:
        scraper.init_browser()
        results,stats,issues = repair_records(read_csv('ufc_fight_results.csv'),fetch_html,args.limit)
    finally:
        scraper.close_browser()
    args.output.mkdir(parents=True)
    write_csv(args.output/'ufc_fight_results.csv',results,RESULT_FIELDS)
    write_csv(args.output/'ufc_fight_stats.csv',stats,STAT_FIELDS)
    (args.output/'repair-report.json').write_text(json.dumps({'requested':args.limit,
        'repaired':len(results),'stat_rows':len(stats),'issues':issues},indent=2),encoding='utf-8')
    print(f'Repaired {len(results)} fights; {len(issues)} failures. Original CSVs unchanged.')
    if issues or not results:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
