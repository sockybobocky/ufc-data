# Early-week prediction inputs

Upcoming cards now have a bounded independent collector. A failure scraping old results or retraining legacy models cannot prevent the upcoming publisher from running. Cards refresh daily at 06:30 UTC; paired US moneylines refresh daily at 12:00 UTC. Both support manual dispatch. These jobs run on GitHub, not the user's computer. Scheduled jobs can be delayed; status timestamps are authoritative.

The odds change increases collection from roughly 8–10 to 28–31 requests monthly, with the existing single US region / h2h market. Existing provider limits and key errors remain failures; old odds are retained and never marked fresh. No free-tier allowance or paid upgrade is assumed.

Main history jobs discard their own changes to independently published card/odds files before rebasing. Their current historical completeness failures are not bypassed. Recent results still need a successful history publication and local import.

Round counts are NOT present in the UFCStats event table currently parsed. The collector explicitly reports that gap; it does not default all bouts to three rounds. Tapology lists per-bout schedules, but its website terms prohibit automated scraping. A licensed API or reviewed source entry is a separate integration, not included in this repair. Cancelled bouts and fighter aliases must be reconciled against exact canonical identities and event date.

The local predictor can calculate read-only previews from frozen winner models without round counts, because those models do not use upcoming round count as an input. Such previews are not original scored forecasts, paper eligibility, or permission to use stale odds. Method/duration forecasts still require schedules. Saved original forecasts and paper records retain the current verification checks.

Validation: fixture-only repository tests; no live API quota consumed and no automated browser scraping run during repair verification. Live workflow validation is still required after merge.
