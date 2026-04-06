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
  pip install requests beautifulsoup4
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
from datetime import datetime

HEADERS = {"User-Agent": "UFC-Stats-Scraper/3.0"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
ODDS_API_KEY = "c60ed248ecaef69dc5662723e95b7ce8"
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
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)


def fetch(url, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, timeout=20)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == retries:
                return None
            time.sleep(1)


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
            if "Height:" in lt: d["HEIGHT"] = lt.split("Height:")[-1].strip()
            elif "Weight:" in lt: d["WEIGHT"] = lt.split("Weight:")[-1].strip()
            elif "Reach:" in lt: d["REACH"] = lt.split("Reach:")[-1].strip()
            elif "tance:" in lt: d["STANCE"] = lt.split(":")[-1].strip()
            elif "DOB:" in lt: d["DOB"] = lt.split("DOB:")[-1].strip()
        details.append(d)
        time.sleep(0.15)
    write_csv("ufc_fighter_tott.csv", tott, ["FIGHTER","SLPM","STR_ACC","SAPM","STR_DEF","TD_AVG","TD_ACC","TD_DEF","SUB_AVG","URL"])
    write_csv("ufc_fighter_details.csv", details, ["FIRST","LAST","NICKNAME","URL","HEIGHT","WEIGHT","REACH","STANCE","DOB"])
    print(f"  -> {len(tott)} tott + {len(details)} details saved")


# ═══════════════════════════════════════════════════
# 3. EVENTS + FIGHT RESULTS + FIGHT STATS
# ═══════════════════════════════════════════════════
def scrape_events_and_fights(state, full=False):
    print("\n[3/8] Scraping events, fight results, and fight stats...")
    resp = fetch("http://www.ufcstats.com/statistics/events/completed?page=all")
    if not resp:
        print("  ERROR: Could not fetch events list")
        return
    soup = BeautifulSoup(resp.text, "html.parser")
    seen = set()
    all_event_urls = []
    for a in soup.select('a[href*="event-details"]'):
        href = a.get("href", "").strip()
        name = a.get_text(strip=True)
        if href and name and href not in seen:
            seen.add(href)
            all_event_urls.append((href, name))
    print(f"  {len(all_event_urls)} total completed events found")

    already = set(state.get("scraped_events", []))
    if full:
        to_scrape = all_event_urls
        already = set()
        state["scraped_events"] = []
    else:
        to_scrape = [(h, n) for h, n in all_event_urls if h not in already]
    print(f"  {len(to_scrape)} events to scrape")

    # Load existing data
    results = []
    fight_stats = []
    if not full and os.path.exists("ufc_fight_results.csv"):
        with open("ufc_fight_results.csv", "r", encoding="utf-8") as f:
            results = list(csv.DictReader(f))
        print(f"  Loaded {len(results)} existing results")
    if not full and os.path.exists("ufc_fight_stats.csv"):
        with open("ufc_fight_stats.csv", "r", encoding="utf-8") as f:
            fight_stats = list(csv.DictReader(f))
        print(f"  Loaded {len(fight_stats)} existing stats")

    for idx, (event_url, event_name) in enumerate(to_scrape):
        print(f"  [{idx+1}/{len(to_scrape)}] {event_name}...", end=" ", flush=True)
        resp2 = fetch(event_url)
        if not resp2:
            continue
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        event_date = ""
        event_location = ""
        for li in soup2.select("li.b-list__box-list-item"):
            lt = li.get_text(" ", strip=True)
            if "Date:" in lt: event_date = lt.split("Date:")[-1].strip()
            elif "Location:" in lt: event_location = lt.split("Location:")[-1].strip()

        fight_rows = soup2.select("tr.b-fight-details__table-row")
        count = 0
        for row in fight_rows:
            fighter_links = row.select('a[href*="fighter-details"]')
            if len(fighter_links) < 2:
                continue
            fa = fighter_links[0].get_text(strip=True)
            fb = fighter_links[1].get_text(strip=True)
            cells = row.select("td")
            cell_texts = [c.get_text(" ", strip=True) for c in cells]

            # Parse W/L from first cell
            wl = cell_texts[0].strip() if cell_texts else ""
            winner = ""
            outcome = ""
            wl_lower = wl.lower()
            if "win" in wl_lower and "loss" in wl_lower:
                winner = fa
                outcome = "W/L"
            elif "loss" in wl_lower and "win" not in wl_lower:
                # This shouldn't happen on event pages but just in case
                winner = fb
                outcome = "L/W"
            elif "win" in wl_lower:
                winner = fa
                outcome = "W/L"
            elif "draw" in wl_lower or "nc" in wl_lower:
                outcome = "D/D"

            weight_class = ""
            method = ""
            rnd = ""
            fight_time = ""
            for ct in cell_texts[1:]:
                ct_s = ct.strip()
                if not ct_s or ct_s == "View Matchup":
                    continue
                if "weight" in ct_s.lower() or "catch" in ct_s.lower() or "open" in ct_s.lower():
                    weight_class = ct_s
                elif ct_s in ["KO/TKO","Submission","Could Not Continue","Overturned"] or "Decision" in ct_s or "DQ" in ct_s:
                    method = ct_s
                elif re.match(r'^\d$', ct_s) and not rnd:
                    rnd = ct_s
                elif re.match(r'^\d+:\d{2}$', ct_s):
                    fight_time = ct_s

            fight_link = row.select_one('a[href*="fight-details"]')
            fight_url = fight_link.get("href", "").strip() if fight_link else ""

            results.append({
                "EVENT": event_name, "DATE": event_date, "BOUT": f"{fa} vs. {fb}",
                "FIGHTER_A": fa, "FIGHTER_B": fb, "WINNER": winner, "OUTCOME": outcome,
                "WEIGHTCLASS": weight_class, "METHOD": method, "ROUND": rnd, "TIME": fight_time,
                "FIGHT_URL": fight_url,
            })
            count += 1

            # Scrape fight detail page for round-by-round stats
            if fight_url and winner:  # Only scrape completed fights
                fstats = scrape_fight_stats(fight_url, event_name, fa, fb)
                fight_stats.extend(fstats)

        print(f"{count} fights")
        state["scraped_events"].append(event_url)
        if (idx + 1) % 25 == 0:
            save_state(state)
            write_csv("ufc_fight_results.csv", results, ["EVENT","DATE","BOUT","FIGHTER_A","FIGHTER_B","WINNER","OUTCOME","WEIGHTCLASS","METHOD","ROUND","TIME","FIGHT_URL"])
            print(f"    checkpoint: {len(results)} results saved")
        time.sleep(0.3)

    write_csv("ufc_fight_results.csv", results, ["EVENT","DATE","BOUT","FIGHTER_A","FIGHTER_B","WINNER","OUTCOME","WEIGHTCLASS","METHOD","ROUND","TIME","FIGHT_URL"])
    write_csv("ufc_fight_stats.csv", fight_stats, ["EVENT","BOUT","ROUND","FIGHTER","KD","SIG.STR.","SIG.STR. %","TOTAL STR.","TD","TD %","SUB.ATT","REV.","CTRL","HEAD","BODY","LEG","DISTANCE","CLINCH","GROUND"])
    save_state(state)
    print(f"  -> {len(results)} results + {len(fight_stats)} stat rows saved")


def scrape_fight_stats(fight_url, event, fa, fb):
    """Scrape round-by-round stats from a fight detail page."""
    stats = []
    resp = fetch(fight_url)
    if not resp:
        return stats
    soup = BeautifulSoup(resp.text, "html.parser")
    bout = f"{fa} vs. {fb}"

    # The fight detail page has sections: Totals and Per Round
    # Each section has two tables: striking totals and significant strikes
    sections = soup.select("section.b-fight-details__section")

    for section in sections:
        # Check if this is per-round or totals
        header = section.select_one("p.b-fight-details__collapse-link_tot, p.b-fight-details__table-title")
        section_text = header.get_text(strip=True) if header else ""
        is_round = "round" in section_text.lower()

        tables = section.select("table")
        for table in tables:
            rows = table.select("tbody tr")
            for ri, row in enumerate(rows):
                cells = row.select("td")
                if len(cells) < 2:
                    continue

                # Each row has one fighter's stats
                fighter_link = cells[0].select_one('a[href*="fighter-details"]')
                if not fighter_link:
                    continue
                fighter_name = fighter_link.get_text(strip=True)
                cell_vals = [c.get_text(strip=True) for c in cells]

                stat = {"EVENT": event, "BOUT": bout, "FIGHTER": fighter_name}
                stat["ROUND"] = str((ri // 2) + 1) if is_round else "Total"

                # Map values to stat keys based on cell count and content
                # Totals table: Fighter, KD, Sig.Str, Sig.Str%, Total Str, TD, TD%, Sub, Rev, Ctrl
                # Sig strikes table: Fighter, Head, Body, Leg, Distance, Clinch, Ground
                vals = cell_vals[1:]  # Skip fighter name cell

                if len(vals) >= 9 and any("%" in v for v in vals[:9]):
                    # This is the main stats table
                    keys = ["KD", "SIG.STR.", "SIG.STR. %", "TOTAL STR.", "TD", "TD %", "SUB.ATT", "REV.", "CTRL"]
                    for ki, key in enumerate(keys):
                        stat[key] = vals[ki] if ki < len(vals) else ""
                elif len(vals) >= 6:
                    # This is the significant strikes by target table
                    keys = ["HEAD", "BODY", "LEG", "DISTANCE", "CLINCH", "GROUND"]
                    for ki, key in enumerate(keys):
                        stat[key] = vals[ki] if ki < len(vals) else ""

                stats.append(stat)

    time.sleep(0.1)
    return stats


# ═══════════════════════════════════════════════════
# 4-8: UPCOMING, ODDS, PROFILES (same as before)
# ═══════════════════════════════════════════════════
def scrape_upcoming_events():
    print("\n[4/8] Scraping upcoming events...")
    fights = []
    resp = fetch("http://www.ufcstats.com/statistics/events/upcoming")
    if not resp: return fights
    soup = BeautifulSoup(resp.text, "html.parser")
    event_links = []
    for a in soup.select('a[href*="event-details"]'):
        href = a.get("href","").strip()
        name = a.get_text(strip=True)
        if href and name and href not in [e[0] for e in event_links]:
            event_links.append((href, name))
    for event_url, event_name in event_links[:5]:
        print(f"  {event_name}...", end=" ", flush=True)
        resp2 = fetch(event_url)
        if not resp2: continue
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        ed = el = ""
        for li in soup2.select("li.b-list__box-list-item"):
            lt = li.get_text(" ", strip=True)
            if "Date:" in lt: ed = lt.split("Date:")[-1].strip()
            elif "Location:" in lt: el = lt.split("Location:")[-1].strip()
        ct = 0
        for row in soup2.select("tr.b-fight-details__table-row"):
            fl = row.select('a[href*="fighter-details"]')
            if len(fl) < 2: continue
            wc = ""
            for cell in row.select("td"):
                t = cell.get_text(strip=True)
                if "weight" in t.lower() or "catch" in t.lower(): wc = t; break
            fights.append({"event_name":event_name,"event_date":ed,"event_location":el,
                "fighter_a":fl[0].get_text(strip=True),"fighter_b":fl[1].get_text(strip=True),
                "fighter_a_url":fl[0].get("href","").strip(),"fighter_b_url":fl[1].get("href","").strip(),
                "weight_class":wc})
            ct += 1
        print(f"{ct} fights")
        time.sleep(0.3)
    write_csv("ufc_upcoming_events.csv", fights, ["event_name","event_date","event_location","fighter_a","fighter_b","fighter_a_url","fighter_b_url","weight_class"])
    print(f"  -> {len(fights)} upcoming fights saved")
    return fights


def fetch_betting_odds():
    print("\n[5/8] Fetching betting odds...")
    odds_data = []
    url = f"https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds?regions=us&markets=h2h&oddsFormat=american&apiKey={ODDS_API_KEY}"
    try:
        resp = SESSION.get(url, timeout=15)
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
    print(f"{'='*60}")
    print(f"UFC Self-Contained Scraper v3.0")
    print(f"Mode: {'FULL HISTORICAL' if full else 'UPDATE'}")
    print(f"Started: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    if full:
        print("\nFULL mode scrapes ALL historical data.")
        print("Fighter profiles: ~1.5 hours | Events+fights: ~1-2 hours")
        print("You only need to run this ONCE. Then use update mode weekly.")
        print("Press Ctrl+C to cancel, or wait 5 seconds...\n")
        try: time.sleep(5)
        except KeyboardInterrupt: print("Cancelled."); return

    state = load_state()

    # Always run these (fast)
    records = scrape_fighter_records()

    # Fighter stats - full only (slow)
    if full:
        scrape_all_fighter_stats(records)
    else:
        print("\n[2/8] Skipping full fighter stats (update mode)")
        if not os.path.exists("ufc_fighter_tott.csv"):
            print("  WARNING: No tott file! Run with --full first.")

    # Events + fights
    scrape_events_and_fights(state, full=full)

    # Always run these (fast)
    scrape_upcoming_events()
    fetch_betting_odds()
    scrape_upcoming_profiles()

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
