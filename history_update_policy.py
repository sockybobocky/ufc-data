"""Separate cached result completeness from explicitly deferred metadata repairs."""


def cached_history_policy(rows):
    retry, verified, deferred = set(), set(), set()
    for row in rows:
        name = row.get('EVENT')
        if not name:
            continue
        # Identity/outcome/finish gaps can represent an unfinished cached card.
        if any(not row.get(field) for field in ('FIGHT_URL', 'OUTCOME', 'ROUND', 'TIME')):
            retry.add(name)
        if row.get('FIGHT_URL') and row.get('OUTCOME'):
            verified.add(name)
        if not row.get('METHOD'):
            deferred.add(name)
    return retry, verified, deferred - retry
