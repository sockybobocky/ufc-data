import unittest
from history_update_policy import cached_history_policy


class HistoryPolicyTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(EVENT='Old card', FIGHT_URL='fight', OUTCOME='W/L', ROUND='3', TIME='5:00', METHOD='')
        row.update(changes)
        return row

    def test_method_only_gap_is_deferred_not_repaired_by_weekly_update(self):
        self.assertEqual(cached_history_policy([self.row()]), (set(), {'Old card'}, {'Old card'}))

    def test_each_missing_result_field_keeps_event_in_retry(self):
        for field in ('FIGHT_URL', 'OUTCOME', 'ROUND', 'TIME'):
            with self.subTest(field=field):
                retry, _, deferred = cached_history_policy([self.row(**{field: ''})])
                self.assertEqual(retry, {'Old card'})
                self.assertEqual(deferred, set())

    def test_one_incomplete_bout_retries_entire_event(self):
        retry, _, deferred = cached_history_policy([self.row(), self.row(FIGHT_URL='')])
        self.assertEqual(retry, {'Old card'})
        self.assertEqual(deferred, set())

    def test_complete_metadata_has_no_deferred_repair(self):
        self.assertEqual(cached_history_policy([self.row(METHOD='Decision')]), (set(), {'Old card'}, set()))

    def test_empty_history_and_unnamed_rows_do_not_create_verified_events(self):
        self.assertEqual(cached_history_policy([]), (set(), set(), set()))
        self.assertEqual(cached_history_policy([self.row(EVENT='')]), (set(), set(), set()))
