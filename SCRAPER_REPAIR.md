# UFCStats scraper repair — review package

This patch preserves the existing data repository and update schedule. It repairs
parsing; it does not replace the upstream source or silently rewrite old records.

## Changes

- Read method, finish round/time and time format from labeled fight-detail metadata.
- Preserve participant URLs, scheduled rounds and explicit round length.
- Keep draws and no contests distinct.
- Match stats to explicit table headers, including the significant-strike columns
  preceding HEAD/BODY/LEG/DISTANCE/CLINCH/GROUND.
- Match rounds to explicit Round N markers instead of table row counts.
- Merge main and targeting rows by fighter URL and round, rejecting conflicts.
- Keep historical time formats intact and mark unsupported formats for review.
- Fail clearly on missing fields, browser checks or incomplete round coverage.
- Abort result/stat publication and event-state advancement on parse/fetch failures.
- Replace results by fight URL and replace stats by fight/event/bout identity;
  rematches in other events are not accidentally skipped by fighter-pair matching.
- Load the odds API key from ODDS_API_KEY rather than embedding it in Python.

## Tests and limits

Fifteen deterministic tests pass. Their HTML is synthetic, modeled on the source's
published field/table structure. They verify correctness and failure behavior;
they do not establish parity against downloaded live fight-page HTML.
Direct HTTPS retrieval was refused and HTTP returned a browser-check document.
That document was not treated as fight data or used to fake a successful sample.

Live verification is required before promotion. The added sample-only GitHub
workflow uses the repository's existing browser environment. It has read-only
repository permissions and writes artifacts rather than committing datasets.
It is manually dispatched; the current Monday/Friday workflow is not triggered
by this local preparation. The sample workflow has not been run or published.

## Review and verify

Apply the included files on a review branch, then run:

```text
python -m unittest test_ufcstats_parser -v
python repair_history.py --limit 5 --output repaired_sample
```

Alternatively run the Verify scraper repair sample workflow on the review branch.
It attempts five known existing fight URLs by default. Inspect its artifacts for
correct source IDs, method, fixed round format, round coverage, targeting values
and outcomes. An issue or failed fetch returns a nonzero status; it never overwrites
the original CSVs. Existing sample output directories are rejected.

The existing update workflow should pass ODDS_API_KEY from a repository secret
when promoted. The sample workflow does not need odds credentials.

After live validation, add these tests to the normal update workflow, preserve
the input snapshot, and perform a checkpointed historical backfill. The bounded
sample utility is deliberately not a full 8,917-fight backfill implementation.
Already-scraped event markers skip old records in ordinary weekly updates, so
publishing a parser fix alone will not repair historical CSVs.

The importer preview must then be updated to use participant URLs, scheduled
round metadata and distinct outcomes before the repaired data is admitted to
PostgreSQL. Automatic feature/model refresh remains a later roadmap step.
