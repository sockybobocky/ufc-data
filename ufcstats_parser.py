"""Pure UFCStats parsing: explicit headers, identities, rounds and outcomes.

Network/browser operations stay in the existing scraper. This module never
executes page scripts or infers a round from the number of table rows.
"""
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

RESULT_FIELDS = ['EVENT','DATE','BOUT','FIGHTER_A','FIGHTER_B','WINNER','OUTCOME',
                 'WEIGHTCLASS','METHOD','ROUND','TIME','FIGHT_URL','FIGHTER_A_URL',
                 'FIGHTER_B_URL','TIME_FORMAT','SCHEDULED_ROUNDS','ROUND_LENGTH_SECONDS']
STAT_FIELDS = ['EVENT','BOUT','ROUND','FIGHTER','KD','SIG.STR.','SIG.STR. %',
               'TOTAL STR.','TD','TD %','SUB.ATT','REV.','CTRL','HEAD','BODY','LEG',
               'DISTANCE','CLINCH','GROUND','FIGHT_URL','FIGHTER_URL']

class ParseError(ValueError):
    pass

def text(node):
    return ' '.join(node.get_text(' ',strip=True).split()) if node else ''

def soup_for(html):
    soup = BeautifulSoup(html,'html.parser')
    if not soup.select('a[href*="fighter-details"]'):
        raise ParseError('Expected fighter links; received incomplete page or browser check')
    return soup

def header_key(value):
    return re.sub(r'[^a-z0-9%]','',value.lower())

HEADERS = {header_key(label):label for label in STAT_FIELDS[4:19]}
HEADERS.update({'sigstr':'SIG.STR.', 'totalstr':'TOTAL STR.', 'subatt':'SUB.ATT',
                'rev':'REV.', 'td':'TD', 'td%':'TD %', 'sigstr%':'SIG.STR. %'})

def labels(soup):
    # Metadata is labeled in text paragraphs; nested tags are flattened once.
    result = {}
    pattern = re.compile(r'(Method|Round|Time format|Time|Referee|Details):\s*',re.I)
    for paragraph in soup.select('p.b-fight-details__text'):
        value = text(paragraph)
        matches = list(pattern.finditer(value))
        for index,match in enumerate(matches):
            end = matches[index+1].start() if index+1 < len(matches) else len(value)
            result[match[1].lower()] = value[match.end():end].strip()
    return result

def round_format(value):
    # Only explicit modern fixed-length formats are automatically importable.
    match = re.fullmatch(r'(\d+)\s+Rnd\s*\((\d+(?:-\d+)*)\)',value.strip(),re.I)
    if not match:
        return '', ''
    rounds = int(match[1])
    lengths = [int(n) for n in match[2].split('-')]
    if not 1 <= rounds <= 5 or len(lengths) != rounds or len(set(lengths)) != 1 or lengths[0] != 5:
        return '', ''
    return str(rounds), str(lengths[0]*60)

def outcome(statuses,names):
    normalized = [s.upper().replace('.','').strip() for s in statuses]
    if normalized == ['W','L']:
        return names[0], 'W/L'
    if normalized == ['L','W']:
        return names[1], 'L/W'
    if normalized == ['D','D']:
        return '', 'D/D'
    if normalized == ['NC','NC']:
        return '', 'NC/NC'
    raise ParseError('Unrecognized outcome statuses: ' + repr(normalized))

def parse_detail(html,fight_url,event='',date=''):
    soup = soup_for(html)
    people = soup.select('.b-fight-details__person')
    if len(people) != 2:
        raise ParseError('Expected two fight participants')
    names,urls,statuses = [],[],[]
    for person in people:
        link = person.select_one('a[href*="fighter-details"]')
        if not link:
            raise ParseError('Participant identity missing')
        names.append(text(link))
        urls.append(urljoin(fight_url,link['href']))
        statuses.append(text(person.select_one('.b-fight-details__person-status')))
    winner,status = outcome(statuses,names)
    fields = labels(soup)
    for required in ('method','round','time','time format'):
        if not fields.get(required):
            raise ParseError('Missing fight detail field: '+required)
    if not re.fullmatch(r'\d+',fields['round']) or not re.fullmatch(r'\d+:\d{2}',fields['time']):
        raise ParseError('Invalid finish round/time')
    minute,second = map(int,fields['time'].split(':'))
    if second >= 60:
        raise ParseError('Invalid finish time seconds')
    rounds,length = round_format(fields['time format'])
    if rounds and (int(fields['round']) > int(rounds) or minute*60+second > int(length)):
        raise ParseError('Finish exceeds explicit round format')
    title = soup.select_one('.b-fight-details__fight-title')
    if not event:
        event_link = soup.select_one('a[href*="event-details"]')
        event = text(event_link)
    return {'EVENT':event,'DATE':date,'BOUT':f'{names[0]} vs. {names[1]}',
        'FIGHTER_A':names[0],'FIGHTER_B':names[1],'WINNER':winner,'OUTCOME':status,
        'WEIGHTCLASS':text(title),'METHOD':fields['method'],'ROUND':fields['round'],
        'TIME':fields['time'],'FIGHT_URL':fight_url,'FIGHTER_A_URL':urls[0],
        'FIGHTER_B_URL':urls[1],'TIME_FORMAT':fields['time format'],
        'SCHEDULED_ROUNDS':rounds,'ROUND_LENGTH_SECONDS':length}

def validate_stat(field,value,round_number):
    if value in ('','--','---'):
        return
    if field in ('KD','SUB.ATT','REV.'):
        if not re.fullmatch(r'\d+',value):
            raise ParseError('Invalid integer field '+field)
    elif field in ('SIG.STR. %','TD %'):
        if not re.fullmatch(r'\d+%',value) or not 0 <= int(value[:-1]) <= 100:
            raise ParseError('Invalid percentage field '+field)
    elif field == 'CTRL':
        match = re.fullmatch(r'(\d+):(\d{2})',value)
        if not match or int(match[2]) >= 60:
            raise ParseError('Invalid control time')
    else:
        match = re.fullmatch(r'(\d+)\s+of\s+(\d+)',value)
        if not match or int(match[1]) > int(match[2]):
            raise ParseError('Invalid landed/attempted field '+field)

def parse_stats(html,fight_url,event,fa,fb):
    soup = soup_for(html)
    records = {}
    expected_names = (fa,fb)
    found_main = False
    for table in soup.select('table'):
        columns = None
        current_round = 'Total'
        for row in table.select('tr'):
            fighter_links = row.select('td a[href*="fighter-details"]')
            if not fighter_links:
                marker = re.fullmatch(r'Round\s+(\d+)',text(row),re.I)
                if marker:
                    current_round = marker[1]
                    continue
                ths = row.find_all('th',recursive=False)
                if ths and header_key(text(ths[0])) == 'fighter':
                    columns = [HEADERS.get(header_key(text(th))) for th in ths[1:]]
                    # UFCStats' main per-round table can label both TD columns
                    # "TD %". Its known nine-field schema distinguishes count from %.
                    if columns == ['KD','SIG.STR.','SIG.STR. %','TOTAL STR.','TD %','TD %','SUB.ATT','REV.','CTRL']:
                        columns[4] = 'TD'
                    if any(key is None for key in columns):
                        raise ParseError('Unknown statistics table header')
                continue
            if columns is None:
                raise ParseError('Statistics row without explicit headers')
            cells = row.find_all('td',recursive=False)
            if len(fighter_links) != 2 or len(cells) != len(columns)+1:
                raise ParseError('Statistics row/header dimensions differ')
            if 'KD' in columns:
                found_main = True
            for side,link in enumerate(fighter_links):
                name = text(link)
                if name not in expected_names:
                    raise ParseError('Unexpected fighter in statistics')
                fighter_url = urljoin(fight_url,link['href'])
                key = (fighter_url,current_round)
                record = records.setdefault(key,{'EVENT':event,'BOUT':f'{fa} vs. {fb}',
                    'ROUND':current_round,'FIGHTER':name,'FIGHT_URL':fight_url,'FIGHTER_URL':fighter_url})
                for field,cell in zip(columns,cells[1:]):
                    values = cell.find_all('p',recursive=False) or cell.find_all('p')
                    if len(values) != 2:
                        raise ParseError('Expected one statistic per fighter')
                    value = text(values[side])
                    validate_stat(field,value,current_round)
                    if field in record and record[field] != value:
                        raise ParseError('Conflicting main/targeting statistics')
                    record[field] = value
    if not found_main:
        raise ParseError('No recognized main statistics table')
    return list(records.values())
