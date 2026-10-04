# ufc-data
Some UFC data for a predictor

## Free-plan odds policy

The independent odds workflow publishes one shared US two-way moneyline snapshot
each day at 12:00 UTC. All local app openings read these files; they do not call
The Odds API. Historical workflows skip the odds request.

`odds_budget.py` permits one provider attempt per UTC date, limits this collector
to 32 paid requests per calendar month, and checks the provider's actual remaining
quota using its free `/sports` endpoint before requesting odds. Collection stops
at a reserve of 25 credits or if the quota cannot be verified. The quota covers
other apps using the same key; the local monthly count covers this collector.

`ufc_odds_usage.json` retains the attempt date and reported allowance between
workflow runs. Manual retries on the same day reuse the existing files without
changing price timestamps. Failed attempts wait until the next UTC date. There
is no paid plan upgrade or historical odds request. Consumers must independently
reject old prices and unmatched bouts.
