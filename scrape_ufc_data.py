"""
UFC Complete Self-Contained Data Scraper
=========================================
Generates ALL CSV files needed for the UFC Fight Predictor.
No external data repos needed — everything from ufcstats.com + The Odds API.

Output files:
  1. ufc_fighter_records.csv    - Fighter W/L/D records
  2. ufc_fighter_tott.csv       - Fighter career stats (SLpM, TDAcc, etc)
  3. ufc_fighter_details.csv    - Fighter bio (height, weight, reach, DOB)
  4. ufc_fight_results.csv      - All fight outcomes
  5. ufc_fight_stats.csv        - Round-by-round fight stats
  6. ufc_upcoming_events.csv    - Upcoming fight cards
  7. ufc_betting_odds.csv       - Current betting odds
  8. ufc_fighter_profiles.csv   - Detailed profiles for upcoming fighters

Usage:
  First run (full historical):  python scrape_ufc_data.py --full
  Weekly update (new only):     python scrape_ufc_data.py

Requirements:
  pip install requests beautifulsoup4 playwright
  python -m playwright install chromium
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import string
import os
import re
import sys
import json
from datetime import datetime, timezone
from ufcstats_parser import ParseError, RESULT_FIELDS, STAT_FIELDS, parse_detail, parse_stats, parse_upcoming, canonical_url, UPCOMING_FIELDS

# Playwright browser - launched once, reused for all ufcstats.com fetches
BROWSER = None
PAGE = None

def init_browser():
    global BROWSER, PAGE
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    BROWSER = pw.chromium.launch(headless=True)
    context = BROWSER.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    PAGE = context.new_page()
    # Solve Cloudflare challenge on first load
    print("  Solving Cloudflare challenge...", end=" ", flush=True)
    PAGE.goto("http://www.ufcstats.com/statistics/fighters?char=a&page=all", timeout=30000)
    try:
        PAGE.wait_for_selector('a[href*="fighter-details"]', timeout=15000)
        print("OK")
    except:
        print("WARNING: challenge may not have resolved")

def close_browser():
    global BROWSER
    if BROWSER:
        BROWSER.close()
        BROWSER = None

# Regular requests session (used only for The Odds API)
API_SESSION = requests.Session()
API_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
STATE_FILE = "scraper_state.json"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_run": None, "scraped_events": []}


def save_state(state):
    state["last_run"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def write_csv(filename, data, fieldnames):
    # Safety: never overwrite existing file with empty data
    if len(data) == 0 and os.path.exists(filename):
        existing_size = os.path.getsize(filename)
        if existing_size > 100:  # File has real data
            print(f"  ⚠️  SKIPPING write to {filename} — got 0 rows but existing file has {existing_size:,} bytes")
            return False
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    return True


def fetch(url, retries=2):
    """Fetch a ufcstats.com page using the Playwright browser."""
    global PAGE
    for attempt in range(retries + 1):
        try:
            PAGE.goto(url, timeout=20000, wait_until="domcontentloaded")
            # Brief wait for dynamic content
            time.sleep(0.3)
            content = PAGE.content()
            if content and len(content) > 500 and "fighter" in content.lower():
                # Return a response-like object
                return type('Resp', (), {'status_code': 200, 'text': content})()
            # If content is small, might still be Cloudflare challenge
            if "Checking your browser" in content:
                time.sleep(3)  # Wait for challenge
                content = PAGE.content()
                if len(content) > 500:
                    return type('Resp', (), {'status_code': 200, 'text': content})()
        except Exception as e:
            if attempt == retries:
                return None
            time.sleep(1)
    return None


# ═══════════════════════════════════════════════════
# 1. FIGHTER RECORDS
# ═══════════════════════════════════════════════════
def scrape_fighter_records():
    print("\n[1/8] Scraping fighter records...")
    all_fighters = []
    for letter in string.ascii_lowercase:
        print(f"  {letter.upper()}...", end=" ", flush=True)
        resp = fetch(f"http://www.ufcstats.com/statistics/fighters?char={letter}&page=all")
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        count = 0
        for row in soup.select("tr"):
            cells = row.select("td")
            if len(cells) < 10:
                continue
            links = row.select('a[href*="fighter-details"]')
            if not links:
                continue
            url = links[0].get("href", "").strip()
            first = cells[0].get_text(strip=True)
            last = cells[1].get_text(strip=True)
            name = f"{first} {last}".strip()
            if not name:
                continue
            all_fighters.append({
                "fighter_name": name, "first_name": first, "last_name": last,
                "nickname": cells[2].get_text(strip=True), "fighter_url": url,
                "height": cells[3].get_text(strip=True), "weight": cells[4].get_text(strip=True),
                "reach": cells[5].get_text(strip=True), "stance": cells[6].get_text(strip=True),
                "wins": cells[7].get_text(strip=True), "losses": cells[8].get_text(strip=True),
                "draws": cells[9].get_text(strip=True),
            })
            count += 1
        print(f"{count}")
        time.sleep(0.3)
    write_csv("ufc_fighter_records.csv", all_fighters, [
        "fighter_name", "first_name", "last_name", "nickname", "fighter_url",
        "height", "weight", "reach", "stance", "wins", "losses", "draws"])
    print(f"  -> {len(all_fighters)} fighters saved")
    return all_fighters


# ═══════════════════════════════════════════════════
# 2. FIGHTER TOTT + DETAILS (from profile pages)
# ═══════════════════════════════════════════════════
def scrape_all_fighter_stats(fighter_records):
    print(f"\n[2/8] Scraping all fighter profile stats ({len(fighter_records)} fighters)...")
    print("  This takes ~1.5-2 hours on first run. Progress saved every 200 fighters.")
    tott = []
    details = []
    total = len(fighter_records)
    for i, fr in enumerate(fighter_records):
        url = fr.get("fighter_url", "")
        name = fr.get("fighter_name", "")
        if not url:
            continue
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{total}] {name}...")
            write_csv("ufc_fighter_tott.csv", tott, ["FIGHTER","SLPM","STR_ACC","SAPM","STR_DEF","TD_AVG","TD_ACC","TD_DEF","SUB_AVG","URL"])
            write_csv("ufc_fighter_details.csv", details, ["FIRST","LAST","NICKNAME","URL","HEIGHT","WEIGHT","REACH","STANCE","DOB"])
        resp = fetch(url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        s = {"FIGHTER": name, "URL": url, "SLPM": "", "STR_ACC": "", "SAPM": "",
             "STR_DEF": "", "TD_AVG": "", "TD_ACC": "", "TD_DEF": "", "SUB_AVG": ""}
        
        # Parse stats from list items - ufcstats uses li.b-list__box-list-item for ALL stats
        for li in soup.select("li.b-list__box-list-item"):
            lt = li.get_text(" ", strip=True)
            # Split on colon to get the value part, then extract number
            if ":" not in lt:
                continue
            label, _, value = lt.partition(":")
            value = value.strip()
            m = re.search(r'([\d.]+)', value)
            if not m:
                continue
            num = m.group(1)
            label_lower = label.lower().strip()
            if "slpm" in label_lower:
                s["SLPM"] = num
            elif "sapm" in label_lower:
                s["SAPM"] = num
            elif "str" in label_lower and "acc" in label_lower:
                s["STR_ACC"] = num
            elif "str" in label_lower and "def" in label_lower:
                s["STR_DEF"] = num
            elif "td" in label_lower and "avg" in label_lower:
                s["TD_AVG"] = num
            elif "td" in label_lower and "acc" in label_lower:
                s["TD_ACC"] = num
            elif "td" in label_lower and "def" in label_lower:
                s["TD_DEF"] = num
            elif "sub" in label_lower and "avg" in label_lower:
                s["SUB_AVG"] = num
        
        tott.append(s)
        
        # Debug: show first 3 fighters' stats to verify extraction
        if len(tott) <= 3:
            print(f"    DEBUG {name}: SLpM={s['SLPM']} SApM={s['SAPM']} StrAcc={s['STR_ACC']} StrDef={s['STR_DEF']} TDAcc={s['TD_ACC']}")
        
        d = {"FIRST": name.split()[0] if name else "", "LAST": " ".join(name.split()[1:]) if name else "",
             "NICKNAME": "", "URL": url, "HEIGHT": "", "WEIGHT": "", "REACH": "", "STANCE": "", "DOB": ""}
        nick = soup.select_one("p.b-content__Nickname")
        if nick:
            d["NICKNAME"] = nick.get_text(strip=True).strip('"')
        for li in soup.select("li.b-list__box-list-item"):
            lt = li.get_text(" ", strip=True)
            lt_lower = lt.lower()
            if "height:" in lt_lower: d["HEIGHT"] = lt.split(":")[-1].strip()
            elif "weight:" in lt_lower: d["WEIGHT"] = lt.split(":")[-1].strip()
            elif "reach:" in lt_lower: d["REACH"] = lt.split(":")[-1].strip()
            elif "stance:" in lt_lower: d["STANCE"] = lt.split(":")[-1].strip()
            elif "dob:" in lt_lower: d["DOB"] = lt.split(":")[-1].strip()
        details.append(d)
        time.sleep(0.15)
    write_csv("ufc_fighter_tott.csv", tott, ["FIGHTER","SLPM","STR_ACC","SAPM","STR_DEF","TD_AVG","TD_ACC","TD_DEF","SUB_AVG","URL"])
    write_csv("ufc_fighter_details.csv", details, ["FIRST","LAST","NICKNAME","URL","HEIGHT","WEIGHT","REACH","STANCE","DOB"])
    print(f"  -> {len(tott)} tott + {len(details)} details saved")


def update_upcoming_fighter_stats():
    """Re-scrape tott + details for upcoming fighters only, merge into existing CSVs."""
    # First scrape upcoming events to know which fighters to update
    resp = fetch("http://www.ufcstats.com/statistics/events/upcoming")
    if not resp:
        print("  Could not fetch upcoming events")
        return
    
    soup = BeautifulSoup(resp.text, "html.parser")
    upcoming_urls = set()
    upcoming_names = {}
    
    for a in soup.select('a[href*="event-details"]'):
        href = a.get("href", "").strip()
        if not href:
            continue
        resp2 = fetch(href)
        if not resp2:
            continue
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        for fl in soup2.select('a[href*="fighter-details"]'):
            furl = fl.get("href", "").strip()
            fname = fl.get_text(strip=True)
            if furl and fname:
                upcoming_urls.add(furl)
                upcoming_names[furl] = fname
        time.sleep(0.3)
    
    if not upcoming_urls:
        print("  No upcoming fighters found")
        return
    
    print(f"  Found {len(upcoming_urls)} upcoming fighters to refresh")
    
    # Load existing tott + details
    existing_tott = {}
    existing_details = {}
    if os.path.exists("ufc_fighter_tott.csv"):
        with open("ufc_fighter_tott.csv", "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                url = row.get("URL", "")
                if url:
                    existing_tott[url] = row
    if os.path.exists("ufc_fighter_details.csv"):
        with open("ufc_fighter_details.csv", "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                url = row.get("URL", "")
                if url:
                    existing_details[url] = row
    
    # Scrape fresh data for upcoming fighters
    updated = 0
    for url in upcoming_urls:
        name = upcoming_names.get(url, "Unknown")
        resp3 = fetch(url)
        if not resp3:
            continue
        soup3 = BeautifulSoup(resp3.text, "html.parser")
        
        # Tott stats
        s = {"FIGHTER": name, "URL": url, "SLPM": "", "STR_ACC": "", "SAPM": "",
             "STR_DEF": "", "TD_AVG": "", "TD_ACC": "", "TD_DEF": "", "SUB_AVG": ""}
        for li in soup3.select("li.b-list__box-list-item"):
            lt = li.get_text(" ", strip=True)
            if ":" not in lt:
                continue
            label, _, value = lt.partition(":")
            value = value.strip()
            m = re.search(r'([\d.]+)', value)
            if not m:
                continue
            num = m.group(1)
            label_lower = label.lower().strip()
            if "slpm" in label_lower: s["SLPM"] = num
            elif "sapm" in label_lower: s["SAPM"] = num
            elif "str" in label_lower and "acc" in label_lower: s["STR_ACC"] = num
            elif "str" in label_lower and "def" in label_lower: s["STR_DEF"] = num
            elif "td" in label_lower and "avg" in label_lower: s["TD_AVG"] = num
            elif "td" in label_lower and "acc" in label_lower: s["TD_ACC"] = num
            elif "td" in label_lower and "def" in label_lower: s["TD_DEF"] = num
            elif "sub" in label_lower and "avg" in label_lower: s["SUB_AVG"] = num
        existing_tott[url] = s
        
        # Details
        d = {"FIRST": name.split()[0] if name else "", "LAST": " ".join(name.split()[1:]) if name else "",
             "NICKNAME": "", "URL": url, "HEIGHT": "", "WEIGHT": "", "REACH": "", "STANCE": "", "DOB": ""}
        nick = soup3.select_one("p.b-content__Nickname")
        if nick:
            d["NICKNAME"] = nick.get_text(strip=True).strip('"')
        for li in soup3.select("li.b-list__box-list-item"):
            lt = li.get_text(" ", strip=True)
            lt_lower = lt.lower()
            if "height:" in lt_lower: d["HEIGHT"] = lt.split(":")[-1].strip()
            elif "weight:" in lt_lower: d["WEIGHT"] = lt.split(":")[-1].strip()
            elif "reach:" in lt_lower: d["REACH"] = lt.split(":")[-1].strip()
            elif "stance:" in lt_lower: d["STANCE"] = lt.split(":")[-1].strip()
            elif "dob:" in lt_lower: d["DOB"] = lt.split(":")[-1].strip()
        existing_details[url] = d
        
        updated += 1
        time.sleep(0.15)
    
    # Write updated CSVs
    write_csv("ufc_fighter_tott.csv", list(existing_tott.values()),
              ["FIGHTER","SLPM","STR_ACC","SAPM","STR_DEF","TD_AVG","TD_ACC","TD_DEF","SUB_AVG","URL"])
    write_csv("ufc_fighter_details.csv", list(existing_details.values()),
              ["FIRST","LAST","NICKNAME","URL","HEIGHT","WEIGHT","REACH","STANCE","DOB"])
    print(f"  -> Refreshed {updated} upcoming fighters in tott + details")


# ═══════════════════════════════════════════════════
# 3. EVENTS + FIGHT RESULTS + FIGHT STATS
# ═══════════════════════════════════════════════════
def scrape_events_and_fights(state, full=False):
    print("\n[3/8] Scraping events, fight results, and fight stats...")
    response = fetch("http://www.ufcstats.com/statistics/events/completed?page=all")
    if response is None:
        raise RuntimeError("Completed-events page retrieval failed")
    soup = BeautifulSoup(response.text, "html.parser")
    event_links = {}
    for link in soup.select('a[href*="event-details"]'):
        if link.get("href") and link.get_text(strip=True):
            event_links[link["href"]] = link.get_text(strip=True)
    if not event_links:
        raise RuntimeError("No completed event links; refusing to replace data")
    already = set() if full else set(state.get("scraped_events", []))
    results, stats = [], []
    if not full:
        for filename, target in (("ufc_fight_results.csv", results), ("ufc_fight_stats.csv", stats)):
            if os.path.exists(filename):
                with open(filename, encoding="utf-8-sig", newline="") as handle:
                    target.extend(csv.DictReader(handle))
    # Cache entries are trusted only when their published results are complete.
    # Older scraper versions marked upcoming/incomplete event pages done.
    retry_names = {r.get("EVENT") for r in results if not r.get("FIGHT_URL") or
                   not r.get("OUTCOME") or not r.get("METHOD") or not r.get("ROUND") or not r.get("TIME")}
    verified_names = {r.get("EVENT") for r in results if r.get("FIGHT_URL") and r.get("OUTCOME")}
    failures = []
    completed = set(already)
    for event_url, event_name in event_links.items():
        if event_url in already and event_name in verified_names and event_name not in retry_names:
            continue
        event_response = fetch(event_url)
        if event_response is None:
            failures.append({"url":event_url,"reason":"Event retrieval failed"})
            continue
        event_soup = BeautifulSoup(event_response.text,"html.parser")
        event_date = ""
        for item in event_soup.select("li.b-list__box-list-item"):
            value = item.get_text(" ",strip=True)
            if "Date:" in value:
                event_date = value.split("Date:",1)[1].strip()
        event_fights = {}
        for link in event_soup.select('a[href*="fight-details"]'):
            event_fights[link["href"]] = None
        if event_date:
            parsed_date = datetime.strptime(event_date, "%B %d, %Y").date()
            if parsed_date > datetime.now(timezone.utc).date() or (parsed_date == datetime.now(timezone.utc).date() and not event_fights):
                completed.discard(event_url)
                continue
        if not event_date or not event_fights:
            failures.append({"url":event_url,"reason":"Missing event date/fights"})
            continue
        event_complete = True
        for fight_url in event_fights:
            try:
                detail_response = fetch(fight_url)
                if detail_response is None:
                    raise RuntimeError("Fight detail retrieval failed")
                fight = parse_detail(detail_response.text,fight_url,event_name,event_date)
                repaired_stats = parse_stats(detail_response.text,fight_url,event_name,fight["FIGHTER_A"],fight["FIGHTER_B"])
                expected = {(name,str(rnd)) for name in (fight["FIGHTER_A"],fight["FIGHTER_B"]) for rnd in range(1,int(fight["ROUND"])+1)}
                present = {(row["FIGHTER"],row["ROUND"]) for row in repaired_stats if row.get("KD") is not None}
                if not expected.issubset(present):
                    raise ParseError("Explicit main round coverage incomplete")
                results = [row for row in results if row.get("FIGHT_URL") != fight_url and not
                           (not row.get("FIGHT_URL") and row.get("EVENT") == event_name and row.get("BOUT") == fight["BOUT"])]
                results.append(fight)
                stats = [row for row in stats if not (row.get("FIGHT_URL") == fight_url or
                         (row.get("EVENT") == event_name and row.get("BOUT") == fight["BOUT"]))]
                stats.extend(repaired_stats)
            except (ParseError, ValueError, RuntimeError) as exc:
                failures.append({"url":fight_url,"reason":str(exc)})
                event_complete = False
            time.sleep(0.3)
        if event_complete:
            # Keep the authoritative completed card, retaining superseded listings in audit evidence.
            results = [r for r in results if r.get("EVENT") != event_name or r.get("FIGHT_URL")]
            completed.add(event_url)
    # Fetch/parse failures must not publish a partial batch or mark failed events done.
    with open("scraper_repair_errors.json","w",encoding="utf-8") as handle:
        json.dump(failures,handle,indent=2)
    if failures:
        raise RuntimeError(f"{len(failures)} scrape failures; result/stat files and event state were not updated")
    write_csv("ufc_fight_results.csv",results,RESULT_FIELDS)
    write_csv("ufc_fight_stats.csv",stats,STAT_FIELDS)
    state["scraped_events"] = sorted(completed)
    save_state(state)
    print(f"  -> {len(results)} results + {len(stats)} statistic rows saved")



def scrape_fight_stats(fight_url, event, fa, fb):
    response = fetch(fight_url)
    if response is None:
        raise RuntimeError("Fight statistics page retrieval failed: " + fight_url)
    return parse_stats(response.text, fight_url, event, fa, fb)



# ═══════════════════════════════════════════════════
# 4-8: UPCOMING, ODDS, PROFILES (same as before)
# ═══════════════════════════════════════════════════
def scrape_upcoming_events():
    print("\n[4/8] Scraping upcoming events...")
    fights = []
    checked_at = datetime.now(timezone.utc).isoformat()
    resp = fetch("http://www.ufcstats.com/statistics/events/upcoming")
    if not resp: raise ParseError("Upcoming index unavailable; prior CSV preserved")
    soup = BeautifulSoup(resp.text, "html.parser")
    event_links = []
    for a in soup.select('a[href*="event-details"]'):
        name = a.get_text(strip=True)
        if not name: continue
        href = canonical_url(a.get("href", ""), "event")
        if href not in [e[0] for e in event_links]: event_links.append((href, name))
    if not event_links: raise ParseError("Upcoming index incomplete; prior CSV preserved")
    for event_url, event_name in event_links[:5]:
        print(f"  {event_name}...", end=" ", flush=True)
        response = fetch(event_url)
        if not response: raise ParseError("Upcoming card unavailable; prior CSV preserved")
        rows = parse_upcoming(response.text, event_url, event_name, checked_at)
        fights.extend(rows)
        print(f"{len(rows)} fights")
        time.sleep(0.3)
    if len({row['fight_url'] for row in fights}) != len(fights):
        raise ParseError("Upcoming fight appears on multiple cards; prior CSV preserved")
    write_csv("ufc_upcoming_events.csv", fights, UPCOMING_FIELDS)
    print(f"  -> {len(fights)} upcoming fights saved")
    return fights


def fetch_betting_odds():
    print("\n[5/8] Fetching betting odds...")
    odds_data = []
    url = f"https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds?regions=us&markets=h2h&oddsFormat=american&apiKey={ODDS_API_KEY}"
    try:
        resp = API_SESSION.get(url, timeout=15)
        resp.raise_for_status()
        fights = resp.json()
        print(f"  {len(fights)} fights with odds")
        for fight in fights:
            fa = fight.get("home_team",""); fb = fight.get("away_team","")
            if not fa or not fb: continue
            oa = []; ob = []
            for book in fight.get("bookmakers",[]):
                for mkt in book.get("markets",[]):
                    if mkt.get("key") != "h2h": continue
                    for o in mkt.get("outcomes",[]):
                        p = o.get("price",0)
                        if not p: continue
                        if o.get("name") == fa: oa.append(p)
                        elif o.get("name") == fb: ob.append(p)
            a = str(oa[0]) if oa else ""; b = str(ob[0]) if ob else ""
            if a and not a.startswith("-"): a = f"+{a}"
            if b and not b.startswith("-"): b = f"+{b}"
            ba = str(max(oa)) if oa else ""; bb = str(max(ob)) if ob else ""
            if ba and not ba.startswith("-"): ba = f"+{ba}"
            if bb and not bb.startswith("-"): bb = f"+{bb}"
            odds_data.append({"event":fight.get("commence_time",""),"fighter_a":fa,"fighter_b":fb,"odds_a":a,"odds_b":b,"best_odds_a":ba,"best_odds_b":bb,"num_books":str(len(oa))})
        remaining = resp.headers.get("x-requests-remaining","?")
        print(f"  API quota: {remaining} remaining")
    except Exception as e:
        print(f"  ERROR: {e}")
    write_csv("ufc_betting_odds.csv", odds_data, ["event","fighter_a","fighter_b","odds_a","odds_b","best_odds_a","best_odds_b","num_books"])
    print(f"  -> {len(odds_data)} odds saved")


def scrape_upcoming_profiles():
    print("\n[6/8] Scraping upcoming fighter profiles...")
    to_scrape = []; seen = set()
    if os.path.exists("ufc_upcoming_events.csv"):
        with open("ufc_upcoming_events.csv","r",encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for k in ["fighter_a_url","fighter_b_url"]:
                    u = row.get(k,"").strip()
                    nk = "fighter_a" if "a" in k else "fighter_b"
                    if u and u not in seen:
                        to_scrape.append({"name":row.get(nk,""),"url":u})
                        seen.add(u)
    print(f"  {len(to_scrape)} fighters")
    data = []
    for i, fighter in enumerate(to_scrape):
        print(f"  [{i+1}/{len(to_scrape)}] {fighter['name']}...", end=" ", flush=True)
        resp = fetch(fighter["url"])
        if not resp: print("SKIP"); continue
        soup = BeautifulSoup(resp.text, "html.parser")
        s = {"fighter_name":fighter["name"],"fighter_url":fighter["url"],
             "slpm":"","str_acc":"","sapm":"","str_def":"","td_avg":"","td_acc":"","td_def":"","sub_avg":""}
        
        # Parse stats from HTML list items
        for li in soup.select("li.b-list__box-list-item"):
            lt = li.get_text(" ", strip=True)
            if ":" not in lt:
                continue
            label, _, value = lt.partition(":")
            value = value.strip()
            m = re.search(r'([\d.]+)', value)
            if not m:
                continue
            num = m.group(1)
            label_lower = label.lower().strip()
            if "slpm" in label_lower:
                s["slpm"] = num
            elif "sapm" in label_lower:
                s["sapm"] = num
            elif "str" in label_lower and "acc" in label_lower:
                s["str_acc"] = num
            elif "str" in label_lower and "def" in label_lower:
                s["str_def"] = num
            elif "td" in label_lower and "avg" in label_lower:
                s["td_avg"] = num
            elif "td" in label_lower and "acc" in label_lower:
                s["td_acc"] = num
            elif "td" in label_lower and "def" in label_lower:
                s["td_def"] = num
            elif "sub" in label_lower and "avg" in label_lower:
                s["sub_avg"] = num
        
        rf = []
        for row in soup.select("tr"):
            rt = row.get_text(" ", strip=True)
            if not re.match(r'^(win|loss|draw|nc)\b', rt, re.I): continue
            result = re.match(r'^(win|loss|draw|nc)\b', rt, re.I).group(1).lower()
            flinks = [a.get_text(strip=True) for a in row.select('a[href*="fighter-details"]')]
            opp = next((n for n in flinks if n.lower() != fighter["name"].lower()), "")
            mm = re.search(r'(KO/TKO|Submission|Decision\s*-\s*\w+|DQ)', rt, re.I)
            method = mm.group(1) if mm else ""
            rm = re.search(r'\b(\d+)\b\s+(\d+:\d{2})', rt)
            rnd = rm.group(1) if rm else ""
            elinks = [a.get_text(strip=True) for a in row.select('a[href*="event-details"]')]
            event = elinks[0] if elinks else ""
            dm = re.search(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4}', rt, re.I)
            date = dm.group(0) if dm else ""
            rf.append({"result":result,"opponent":opp,"method":method,"end_round":rnd,"event":event,"date":date})
        s["recent_fights_count"] = str(len(rf))
        for j, fight in enumerate(rf[:10]):
            for fk in ["result","opponent","method","end_round","event","date"]:
                kk = "round" if fk == "end_round" else fk
                s[f"fight_{j}_{kk}"] = fight[fk]
        data.append(s)
        print("OK")
        time.sleep(0.3)
    ak = set()
    for d in data: ak.update(d.keys())
    fn = ["fighter_name","fighter_url","slpm","str_acc","sapm","str_def","td_avg","td_acc","td_def","sub_avg","recent_fights_count"]
    for k in sorted(ak):
        if k not in fn: fn.append(k)
    write_csv("ufc_fighter_profiles.csv", data, fn)
    print(f"  -> {len(data)} profiles saved")


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════
def main():
    start = datetime.now()
    full = "--full" in sys.argv
    fight_stats_only = "--fight-stats" in sys.argv
    print(f"{'='*60}")
    print(f"UFC Self-Contained Scraper v3.0")
    mode_label = "FIGHT STATS ONLY" if fight_stats_only else ("FULL HISTORICAL" if full else "UPDATE")
    print(f"Mode: {mode_label}")
    print(f"Started: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    if fight_stats_only:
        # Only re-scrape fight detail pages for round-by-round stats
        if not os.path.exists("ufc_fight_results.csv"):
            print("ERROR: ufc_fight_results.csv not found. Run --full first.")
            return
        
        print("\nLoading existing fight results...")
        with open("ufc_fight_results.csv", "r", encoding="utf-8") as f:
            results = list(csv.DictReader(f))
        
        fight_urls = [(r.get("FIGHT_URL",""), r.get("EVENT",""), r.get("FIGHTER_A",""), r.get("FIGHTER_B","")) 
                      for r in results if r.get("FIGHT_URL","").strip() and r.get("WINNER","").strip()]
        print(f"Found {len(fight_urls)} completed fights with URLs")
        
        # Load existing fight stats to skip fights that already have per-round data
        fights_with_rounds = set()
        if os.path.exists("ufc_fight_stats.csv"):
            with open("ufc_fight_stats.csv", "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    rnd = row.get("ROUND", "")
                    if rnd and rnd not in ("Total", "total", ""):
                        fights_with_rounds.add(row.get("BOUT", ""))
            # Keep existing stats that already have per-round data
            with open("ufc_fight_stats.csv", "r", encoding="utf-8") as f:
                all_stats = list(csv.DictReader(f))
            print(f"  {len(fights_with_rounds)} fights already have per-round data (will skip)")
            print(f"  {len(all_stats)} existing stat rows loaded")
            # Filter to only scrape fights missing per-round data
            fight_urls = [(u, e, fa, fb) for u, e, fa, fb in fight_urls 
                          if f"{fa} vs. {fb}" not in fights_with_rounds]
            print(f"  {len(fight_urls)} fights still need per-round data")
        
        print("\nLaunching browser...")
        init_browser()
        
        all_stats = []
        try:
            for i, (url, event, fa, fb) in enumerate(fight_urls):
                if (i + 1) % 100 == 0:
                    print(f"  [{i+1}/{len(fight_urls)}] {fa} vs {fb}...")
                    write_csv("ufc_fight_stats.csv", all_stats, 
                              ["EVENT","BOUT","ROUND","FIGHTER","KD","SIG.STR.","SIG.STR. %","TOTAL STR.","TD","TD %","SUB.ATT","REV.","CTRL","HEAD","BODY","LEG","DISTANCE","CLINCH","GROUND"])
                    print(f"    checkpoint: {len(all_stats)} stat rows saved")
                
                fstats = scrape_fight_stats(url, event, fa, fb)
                all_stats.extend(fstats)
        except KeyboardInterrupt:
            print(f"\n  Interrupted at fight {i+1}. Saving {len(all_stats)} stat rows...")
        finally:
            close_browser()
        
        write_csv("ufc_fight_stats.csv", all_stats,
                  ["EVENT","BOUT","ROUND","FIGHTER","KD","SIG.STR.","SIG.STR. %","TOTAL STR.","TD","TD %","SUB.ATT","REV.","CTRL","HEAD","BODY","LEG","DISTANCE","CLINCH","GROUND"])
        
        # Count per-round rows
        round_rows = sum(1 for s in all_stats if s.get("ROUND") not in ("Total", "total", ""))
        print(f"\n  -> {len(all_stats)} total rows ({round_rows} per-round rows) saved")
        
        elapsed = (datetime.now() - start).total_seconds()
        print(f"Done in {elapsed:.0f}s ({elapsed/60:.1f} min)")
        return

    if full:
        print("\nFULL mode scrapes ALL historical data.")
        print("Fighter profiles: ~1.5 hours | Events+fights: ~1-2 hours")
        print("You only need to run this ONCE. Then use update mode weekly.")
        print("Press Ctrl+C to cancel, or wait 5 seconds...\n")
        try: time.sleep(5)
        except KeyboardInterrupt: print("Cancelled."); return

    state = load_state()

    # Launch headless browser for ufcstats.com (bypasses Cloudflare)
    print("\nLaunching browser...")
    init_browser()

    try:
        # Always run these (fast)
        records = scrape_fighter_records()

        # Fighter stats - full only (slow)
        if full:
            scrape_all_fighter_stats(records)
        else:
            print("\n[2/8] Updating stats for upcoming fighters only...")
            if not os.path.exists("ufc_fighter_tott.csv"):
                print("  WARNING: No tott file! Run with --full first.")
            else:
                update_upcoming_fighter_stats()

        # Events + fights
        scrape_events_and_fights(state, full=full)

        # Upcoming events + profiles (need browser)
        scrape_upcoming_events()
        scrape_upcoming_profiles()
    finally:
        close_browser()
        print("  Browser closed.")

    # Odds API doesn't need browser
    fetch_betting_odds()

    print("\n[7/8] Reserved\n[8/8] Reserved")

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{'='*60}")
    print(f"Done in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"\nFiles:")
    for f in ["ufc_fighter_records.csv","ufc_fighter_tott.csv","ufc_fighter_details.csv",
              "ufc_fight_results.csv","ufc_fight_stats.csv","ufc_upcoming_events.csv",
              "ufc_betting_odds.csv","ufc_fighter_profiles.csv"]:
        if os.path.exists(f):
            sz = os.path.getsize(f)
            with open(f,"r",encoding="utf-8") as fh: lines = sum(1 for _ in fh)-1
            print(f"  {'Y' if lines > 0 else 'X'} {f} ({lines:,} rows, {sz:,} bytes)")
        else:
            print(f"  X {f} (missing)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
