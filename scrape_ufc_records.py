"""
UFC Fighter Records Scraper
============================
Scrapes W/L records, height, weight, reach, stance from ufcstats.com
and saves to a CSV file. Run this on a schedule (daily/weekly) to keep
the data fresh.

Usage:
    python scrape_ufc_records.py

Output:
    ufc_fighter_records.csv

Requirements:
    pip install requests beautifulsoup4

Optional auto-scheduling:
    - Windows: Use Task Scheduler
    - Mac/Linux: Use cron (e.g. 0 6 * * 1 python /path/to/scrape_ufc_records.py)
    - GitHub Actions: See comments at bottom of file
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import string
import os
from datetime import datetime

OUTPUT_FILE = "ufc_fighter_records.csv"
BASE_URL = "http://www.ufcstats.com/statistics/fighters"
HEADERS = {"User-Agent": "UFC-Stats-Scraper/1.0"}


def scrape_letter(letter):
    """Scrape all fighters for a given letter."""
    fighters = []
    url = f"{BASE_URL}?char={letter}&page=all"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Error fetching letter {letter}: {e}")
        return fighters
    
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("tr")
    
    for row in rows:
        cells = row.select("td")
        if len(cells) < 10:
            continue
        
        links = row.select('a[href*="fighter-details"]')
        if not links:
            continue
        
        fighter_url = links[0].get("href", "").strip()
        first_name = cells[0].get_text(strip=True)
        last_name = cells[1].get_text(strip=True)
        nickname = cells[2].get_text(strip=True)
        height = cells[3].get_text(strip=True)
        weight = cells[4].get_text(strip=True)
        reach = cells[5].get_text(strip=True)
        stance = cells[6].get_text(strip=True)
        wins = cells[7].get_text(strip=True)
        losses = cells[8].get_text(strip=True)
        draws = cells[9].get_text(strip=True)
        
        full_name = f"{first_name} {last_name}".strip()
        if not full_name:
            continue
        
        fighters.append({
            "fighter_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "nickname": nickname,
            "fighter_url": fighter_url,
            "height": height,
            "weight": weight,
            "reach": reach,
            "stance": stance,
            "wins": wins,
            "losses": losses,
            "draws": draws,
        })
    
    return fighters


def main():
    print(f"UFC Fighter Records Scraper")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    all_fighters = []
    
    for letter in string.ascii_lowercase:
        print(f"  Scraping letter {letter.upper()}...", end=" ", flush=True)
        fighters = scrape_letter(letter)
        all_fighters.extend(fighters)
        print(f"{len(fighters)} fighters")
        time.sleep(0.5)  # be nice to the server
    
    print(f"{'='*50}")
    print(f"Total fighters scraped: {len(all_fighters)}")
    
    # Write CSV
    fieldnames = [
        "fighter_name", "first_name", "last_name", "nickname",
        "fighter_url", "height", "weight", "reach", "stance",
        "wins", "losses", "draws"
    ]
    
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_fighters)
    
    file_size = os.path.getsize(OUTPUT_FILE)
    print(f"Saved to: {OUTPUT_FILE} ({file_size:,} bytes)")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()


# ============================================================
# GITHUB ACTIONS AUTO-UPDATE (optional)
# ============================================================
# To auto-update the CSV weekly using GitHub Actions for free:
#
# 1. Create a GitHub repo and push this script + the CSV
# 2. Create .github/workflows/update.yml with this content:
#
# name: Update UFC Records
# on:
#   schedule:
#     - cron: '0 6 * * 1'  # Every Monday at 6am UTC
#   workflow_dispatch:       # Manual trigger button
#
# jobs:
#   scrape:
#     runs-on: ubuntu-latest
#     steps:
#       - uses: actions/checkout@v4
#       - uses: actions/setup-python@v5
#         with:
#           python-version: '3.12'
#       - run: pip install requests beautifulsoup4
#       - run: python scrape_ufc_records.py
#       - run: |
#           git config user.name "github-actions"
#           git config user.email "actions@github.com"
#           git add ufc_fighter_records.csv
#           git diff --cached --quiet || git commit -m "Update UFC records $(date +%Y-%m-%d)"
#           git push
#
# 3. Then in the app, just fetch YOUR repo's CSV instead of scraping:
#    https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/ufc_fighter_records.csv
