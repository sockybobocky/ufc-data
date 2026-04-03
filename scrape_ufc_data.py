"""
UFC Complete Data Scraper
==========================
Generates multiple CSV files for the UFC Fight Predictor app:

1. ufc_fighter_records.csv    - Fighter W/L/D, height, weight, reach, stance
2. ufc_upcoming_events.csv    - Upcoming fight cards with all matchups
3. ufc_betting_odds.csv       - Current betting odds from BestFightOdds
4. ufc_fighter_stats.csv      - Per-fighter aggregated career stats
5. ufc_fight_history.csv      - Per-fighter recent fight history (last 10 fights)

Requirements:
    pip install requests beautifulsoup4

Usage:
    python scrape_ufc_data.py

Auto-update via GitHub Actions — see update.yml
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import string
import os
import re
from datetime import datetime
from collections import defaultdict

HEADERS = {"User-Agent": "UFC-Stats-Scraper/2.0"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ═══════════════════════════════════════════════════
# 1. FIGHTER RECORDS (W/L, physical stats)
# ═══════════════════════════════════════════════════
def scrape_fighter_records():
    print("\n[1/5] Scraping fighter records from ufcstats.com...")
    all_fighters = []

    for letter in string.ascii_lowercase:
        print(f"  Letter {letter.upper()}...", end=" ", flush=True)
        url = f"http://www.ufcstats.com/statistics/fighters?char={letter}&page=all"
        try:
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("tr")
            count = 0
            for row in rows:
                cells = row.select("td")
                if len(cells) < 10:
                    continue
                links = row.select('a[href*="fighter-details"]')
                if not links:
                    continue
                fighter_url = links[0].get("href", "").strip()
                first = cells[0].get_text(strip=True)
                last = cells[1].get_text(strip=True)
                nickname = cells[2].get_text(strip=True)
                height = cells[3].get_text(strip=True)
                weight = cells[4].get_text(strip=True)
                reach = cells[5].get_text(strip=True)
                stance = cells[6].get_text(strip=True)
                wins = cells[7].get_text(strip=True)
                losses = cells[8].get_text(strip=True)
                draws = cells[9].get_text(strip=True)
                name = f"{first} {last}".strip()
                if not name:
                    continue
                all_fighters.append({
                    "fighter_name": name, "first_name": first, "last_name": last,
                    "nickname": nickname, "fighter_url": fighter_url,
                    "height": height, "weight": weight, "reach": reach,
                    "stance": stance, "wins": wins, "losses": losses, "draws": draws,
                })
                count += 1
            print(f"{count} fighters")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(0.3)

    write_csv("ufc_fighter_records.csv", all_fighters, [
        "fighter_name", "first_name", "last_name", "nickname", "fighter_url",
        "height", "weight", "reach", "stance", "wins", "losses", "draws"
    ])
    print(f"  → Saved {len(all_fighters)} fighters to ufc_fighter_records.csv")
    return all_fighters


# ═══════════════════════════════════════════════════
# 2. UPCOMING EVENTS (fight cards)
# ═══════════════════════════════════════════════════
def scrape_upcoming_events():
    print("\n[2/5] Scraping upcoming events from ufcstats.com...")
    events = []
    fights = []

    try:
        resp = SESSION.get("http://www.ufcstats.com/statistics/events/upcoming", timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        event_links = []
        for a in soup.select('a[href*="event-details"]'):
            href = a.get("href", "").strip()
            name = a.get_text(strip=True)
            if href and name and href not in [e[0] for e in event_links]:
                event_links.append((href, name))

        print(f"  Found {len(event_links)} upcoming events")

        for event_url, event_name in event_links[:5]:  # Limit to next 5 events
            print(f"  Scraping: {event_name}...", end=" ", flush=True)
            try:
                resp2 = SESSION.get(event_url, timeout=15)
                resp2.raise_for_status()
                soup2 = BeautifulSoup(resp2.text, "html.parser")

                # Get event date and location
                date_el = soup2.select_one("li.b-list__box-list-item")
                event_date = ""
                event_location = ""
                for li in soup2.select("li.b-list__box-list-item"):
                    text = li.get_text(strip=True)
                    if "Date:" in text:
                        event_date = text.replace("Date:", "").strip()
                    elif "Location:" in text:
                        event_location = text.replace("Location:", "").strip()

                events.append({
                    "event_name": event_name,
                    "event_url": event_url,
                    "event_date": event_date,
                    "event_location": event_location,
                })

                # Get fight card
                fight_rows = soup2.select("tr.b-fight-details__table-row")
                fight_count = 0
                for row in fight_rows:
                    fighter_links = row.select('a[href*="fighter-details"]')
                    if len(fighter_links) < 2:
                        continue
                    fighter_a = fighter_links[0].get_text(strip=True)
                    fighter_b = fighter_links[1].get_text(strip=True)
                    fighter_a_url = fighter_links[0].get("href", "").strip()
                    fighter_b_url = fighter_links[1].get("href", "").strip()

                    # Weight class from the row
                    cells = row.select("td")
                    weight_class = ""
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        if "weight" in text.lower() or "catch" in text.lower():
                            weight_class = text
                            break

                    fights.append({
                        "event_name": event_name,
                        "event_date": event_date,
                        "event_location": event_location,
                        "fighter_a": fighter_a,
                        "fighter_b": fighter_b,
                        "fighter_a_url": fighter_a_url,
                        "fighter_b_url": fighter_b_url,
                        "weight_class": weight_class,
                    })
                    fight_count += 1

                print(f"{fight_count} fights")
            except Exception as e:
                print(f"ERROR: {e}")
            time.sleep(0.5)

    except Exception as e:
        print(f"  ERROR fetching events page: {e}")

    write_csv("ufc_upcoming_events.csv", fights, [
        "event_name", "event_date", "event_location",
        "fighter_a", "fighter_b", "fighter_a_url", "fighter_b_url", "weight_class"
    ])
    print(f"  → Saved {len(fights)} upcoming fights to ufc_upcoming_events.csv")
    return fights


# ═══════════════════════════════════════════════════
# 3. BETTING ODDS from The Odds API (free, reliable)
# ═══════════════════════════════════════════════════
def scrape_betting_odds():
    print("\n[3/5] Fetching betting odds from The Odds API...")
    odds_data = []

    API_KEY = "c60ed248ecaef69dc5662723e95b7ce8"
    url = f"https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds?regions=us&markets=h2h&oddsFormat=american&apiKey={API_KEY}"

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        fights = resp.json()

        print(f"  API returned {len(fights)} upcoming fights with odds")

        for fight in fights:
            fighter_a = fight.get("home_team", "")
            fighter_b = fight.get("away_team", "")
            commence = fight.get("commence_time", "")
            if not fighter_a or not fighter_b:
                continue

            # Collect odds from all bookmakers
            all_odds_a = []
            all_odds_b = []

            for book in fight.get("bookmakers", []):
                for market in book.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        name = outcome.get("name", "")
                        price = outcome.get("price", 0)
                        if not price:
                            continue
                        if name == fighter_a:
                            all_odds_a.append(price)
                        elif name == fighter_b:
                            all_odds_b.append(price)

            # Use first bookmaker's odds as the primary display odds
            odds_a = str(all_odds_a[0]) if all_odds_a else ""
            odds_b = str(all_odds_b[0]) if all_odds_b else ""

            # Add + prefix for positive odds
            if odds_a and not odds_a.startswith("-"):
                odds_a = f"+{odds_a}"
            if odds_b and not odds_b.startswith("-"):
                odds_b = f"+{odds_b}"

            # Best available odds (most favorable for each fighter)
            best_a = str(max(all_odds_a)) if all_odds_a else ""
            best_b = str(max(all_odds_b)) if all_odds_b else ""
            if best_a and not best_a.startswith("-"):
                best_a = f"+{best_a}"
            if best_b and not best_b.startswith("-"):
                best_b = f"+{best_b}"

            odds_data.append({
                "event": commence,
                "fighter_a": fighter_a,
                "fighter_b": fighter_b,
                "odds_a": odds_a,
                "odds_b": odds_b,
                "best_odds_a": best_a,
                "best_odds_b": best_b,
                "num_books": str(len(all_odds_a)),
            })

        # Show remaining API quota
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        print(f"  API quota: {used} used, {remaining} remaining this month")

    except Exception as e:
        print(f"  ERROR: {e}")

    write_csv("ufc_betting_odds.csv", odds_data, [
        "event", "fighter_a", "fighter_b", "odds_a", "odds_b",
        "best_odds_a", "best_odds_b", "num_books"
    ])
    print(f"  → Saved {len(odds_data)} matchup odds to ufc_betting_odds.csv")
    return odds_data


# ═══════════════════════════════════════════════════
# 4. PER-FIGHTER AGGREGATED STATS
# ═══════════════════════════════════════════════════
def scrape_fighter_detailed_stats(fighter_records):
    """
    Scrape individual fighter profile pages for detailed career stats.
    Only scrapes fighters who are in upcoming events or top ranked to keep it fast.
    """
    print("\n[4/5] Scraping detailed fighter stats from profiles...")

    # Build list of fighters to scrape (prioritize upcoming + top fighters)
    fighters_to_scrape = []
    urls_seen = set()

    # Read upcoming events to know which fighters need stats
    if os.path.exists("ufc_upcoming_events.csv"):
        with open("ufc_upcoming_events.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for key in ["fighter_a_url", "fighter_b_url"]:
                    url = row.get(key, "").strip()
                    if url and url not in urls_seen:
                        name = row.get("fighter_a" if "a" in key else "fighter_b", "")
                        fighters_to_scrape.append({"name": name, "url": url})
                        urls_seen.add(url)

    print(f"  Scraping {len(fighters_to_scrape)} fighter profiles (upcoming fighters)...")
    stats_data = []

    for i, fighter in enumerate(fighters_to_scrape):
        print(f"  [{i+1}/{len(fighters_to_scrape)}] {fighter['name']}...", end=" ", flush=True)
        try:
            resp = SESSION.get(fighter["url"], timeout=15)
            resp.raise_for_status()
            text = resp.text
            soup = BeautifulSoup(text, "html.parser")
            body_text = soup.get_text(" ", strip=True)

            # Extract career stats
            stats = {"fighter_name": fighter["name"], "fighter_url": fighter["url"]}

            patterns = {
                "slpm": r"SLpM\s*:?\s*([\d.]+)",
                "str_acc": r"Str\.?\s*Acc\.?\s*:?\s*([\d.]+)%?",
                "sapm": r"SApM\s*:?\s*([\d.]+)",
                "str_def": r"Str\.?\s*Def\.?\s*:?\s*([\d.]+)%?",
                "td_avg": r"TD\s*Avg\.?\s*:?\s*([\d.]+)",
                "td_acc": r"TD\s*Acc\.?\s*:?\s*([\d.]+)%?",
                "td_def": r"TD\s*Def\.?\s*:?\s*([\d.]+)%?",
                "sub_avg": r"Sub\.?\s*Avg\.?\s*:?\s*([\d.]+)",
            }

            for key, pattern in patterns.items():
                m = re.search(pattern, body_text)
                stats[key] = m.group(1) if m else ""

            # Extract recent fight history
            recent_fights = []
            fight_rows = soup.select("tr")
            for row in fight_rows:
                row_text = row.get_text(" ", strip=True)
                if not re.match(r'^(win|loss|draw|nc)\b', row_text, re.I):
                    continue

                result_match = re.match(r'^(win|loss|draw|nc)\b', row_text, re.I)
                result = result_match.group(1).lower() if result_match else ""

                fighter_links = [a.get_text(strip=True) for a in row.select('a[href*="fighter-details"]')]
                opponent = ""
                for name in fighter_links:
                    if name.lower() != fighter["name"].lower():
                        opponent = name
                        break

                method_match = re.search(r'(KO/TKO|Submission|Decision\s*-\s*\w+|DQ)', row_text, re.I)
                method = method_match.group(1) if method_match else ""

                round_match = re.search(r'\b(\d+)\b\s+(\d+:\d{2})', row_text)
                end_round = round_match.group(1) if round_match else ""

                event_links = [a.get_text(strip=True) for a in row.select('a[href*="event-details"]')]
                event = event_links[0] if event_links else ""

                date_match = re.search(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4}', row_text, re.I)
                date = date_match.group(0) if date_match else ""

                recent_fights.append({
                    "result": result, "opponent": opponent, "method": method,
                    "end_round": end_round, "event": event, "date": date,
                })

            stats["recent_fights_count"] = str(len(recent_fights))
            # Store last 10 fights as pipe-delimited
            for j, fight in enumerate(recent_fights[:10]):
                stats[f"fight_{j}_result"] = fight["result"]
                stats[f"fight_{j}_opponent"] = fight["opponent"]
                stats[f"fight_{j}_method"] = fight["method"]
                stats[f"fight_{j}_round"] = fight["end_round"]
                stats[f"fight_{j}_event"] = fight["event"]
                stats[f"fight_{j}_date"] = fight["date"]

            stats_data.append(stats)
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(0.4)

    # Build dynamic fieldnames from all collected stats
    all_keys = set()
    for s in stats_data:
        all_keys.update(s.keys())
    fieldnames = ["fighter_name", "fighter_url", "slpm", "str_acc", "sapm", "str_def",
                  "td_avg", "td_acc", "td_def", "sub_avg", "recent_fights_count"]
    for key in sorted(all_keys):
        if key not in fieldnames:
            fieldnames.append(key)

    write_csv("ufc_fighter_profiles.csv", stats_data, fieldnames)
    print(f"  → Saved {len(stats_data)} fighter profiles to ufc_fighter_profiles.csv")
    return stats_data


# ═══════════════════════════════════════════════════
# 5. FIGHT HISTORY (recent fights per fighter)
# ═══════════════════════════════════════════════════
def build_fight_history(fighter_records):
    """Build fight history from existing fight results CSV if available."""
    print("\n[5/5] Building fight history index...")

    # Check if Greco1899 fight results exist
    fight_file = "ufc_fight_results.csv"
    if not os.path.exists(fight_file):
        print(f"  {fight_file} not found. Skipping fight history build.")
        print("  (Download from github.com/Greco1899/scrape_ufc_stats if you want this)")
        return []

    # Read and index by fighter
    history = defaultdict(list)
    with open(fight_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fa = row.get("fighter_a", "").strip()
            fb = row.get("fighter_b", "").strip()
            winner = row.get("winner", "").strip()
            fight = {
                "opponent": "", "result": "", "method": row.get("method", "").strip(),
                "round": row.get("last_round", "").strip(),
                "event": row.get("event", "").strip(),
                "date": row.get("date", "").strip(),
            }
            if fa:
                entry_a = dict(fight)
                entry_a["opponent"] = fb
                entry_a["result"] = "win" if winner == fa else ("loss" if winner == fb else "other")
                history[fa.lower()].append(entry_a)
            if fb:
                entry_b = dict(fight)
                entry_b["opponent"] = fa
                entry_b["result"] = "win" if winner == fb else ("loss" if winner == fa else "other")
                history[fb.lower()].append(entry_b)

    # Write per-fighter last 10 fights
    output = []
    for name_lower, fights in history.items():
        last_10 = fights[-10:]  # Most recent
        for i, fight in enumerate(reversed(last_10)):
            output.append({
                "fighter_name": name_lower,
                "fight_num": str(i + 1),
                "opponent": fight["opponent"],
                "result": fight["result"],
                "method": fight["method"],
                "round": fight["round"],
                "event": fight["event"],
                "date": fight["date"],
            })

    write_csv("ufc_fight_history.csv", output, [
        "fighter_name", "fight_num", "opponent", "result",
        "method", "round", "event", "date"
    ])
    print(f"  → Saved {len(output)} fight history entries to ufc_fight_history.csv")
    return output


# ═══════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════
def write_csv(filename, data, fieldnames):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)


def main():
    start = datetime.now()
    print(f"{'='*60}")
    print(f"UFC Complete Data Scraper")
    print(f"Started: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    fighter_records = scrape_fighter_records()
    scrape_upcoming_events()
    scrape_betting_odds()
    scrape_fighter_detailed_stats(fighter_records)
    build_fight_history(fighter_records)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{'='*60}")
    print(f"All done in {elapsed:.0f} seconds!")
    print(f"Files generated:")
    for f in ["ufc_fighter_records.csv", "ufc_upcoming_events.csv",
              "ufc_betting_odds.csv", "ufc_fighter_profiles.csv", "ufc_fight_history.csv"]:
        if os.path.exists(f):
            size = os.path.getsize(f)
            print(f"  ✓ {f} ({size:,} bytes)")
        else:
            print(f"  ✗ {f} (not generated)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
