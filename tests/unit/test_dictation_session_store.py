#!/usr/bin/env python3
"""
Unit tests for DictationSessionStore.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.dictation_session_store import DictationSessionStore


class TestDictationSessionStore(unittest.TestCase):
    def _at(self, timestamp: float):
        return patch("src.dictation_session_store.time.time", return_value=timestamp)

    def test_lifecycle_dictation_to_processing_to_complete(self):
        store = DictationSessionStore(max_results=10, ttl_seconds=600)

        with self._at(1000.0):
            session_id = store.begin_session(suppress_paste=True, source="followup")
            snapshot = store.get_status_snapshot()

        self.assertEqual(snapshot.get("activeSessionId"), session_id)
        self.assertEqual(snapshot.get("audioLevel"), 0)

        with self._at(1001.0):
            marked = store.mark_processing()
        self.assertEqual(marked, session_id)

        with self._at(1002.0):
            outcome = store.complete_active(
                processed_text="hello world",
                history_entry_id="hist_1",
                completed_at=1002.0,
            )
            result = store.get_session_result(session_id)
            final_snapshot = store.get_status_snapshot()

        self.assertEqual(outcome.get("sessionId"), session_id)
        self.assertTrue(outcome.get("suppressPaste"))
        self.assertEqual(result.get("state"), "complete")
        self.assertEqual(result.get("processedTranscript"), "hello world")
        self.assertEqual(result.get("historyEntryId"), "hist_1")
        self.assertIsNone(final_snapshot.get("activeSessionId"))
        self.assertEqual(final_snapshot.get("lastCompletedSessionId"), session_id)

    def test_stop_session_validation(self):
        store = DictationSessionStore(max_results=10, ttl_seconds=600)

        with self._at(2000.0):
            session_id = store.begin_session(suppress_paste=False, source="test")

        self.assertTrue(store.is_stop_session_valid(None))
        self.assertTrue(store.is_stop_session_valid(session_id))
        self.assertFalse(store.is_stop_session_valid("sess_other"))

        with self._at(2001.0):
            store.clear_active(as_not_found=True)
            result = store.get_session_result(session_id)

        self.assertFalse(store.is_stop_session_valid(session_id))
        self.assertEqual(result.get("state"), "not_found")

    def test_ttl_eviction_for_inactive_sessions(self):
        store = DictationSessionStore(max_results=10, ttl_seconds=60)

        with self._at(3000.0):
            session_id = store.begin_session(suppress_paste=False, source="ttl_test")
        with self._at(3001.0):
            store.mark_processing()
            store.complete_active(
                processed_text="old",
                history_entry_id="hist_old",
                completed_at=3001.0,
            )

        with self._at(3060.0):
            still_present = store.get_session_result(session_id)
        self.assertEqual(still_present.get("state"), "complete")

        with self._at(3062.0):
            store.get_status_snapshot()  # triggers eviction scan
            evicted = store.get_session_result(session_id)
        self.assertEqual(evicted.get("state"), "not_found")

    def test_ttl_does_not_evict_active_session(self):
        store = DictationSessionStore(max_results=10, ttl_seconds=60)

        with self._at(4000.0):
            session_id = store.begin_session(suppress_paste=False, source="active_ttl")

        with self._at(4200.0):
            snapshot = store.get_status_snapshot()
            result = store.get_session_result(session_id, audio_state="dictation")

        self.assertEqual(snapshot.get("activeSessionId"), session_id)
        self.assertEqual(result.get("state"), "dictation")

    def test_max_results_cap_evicts_oldest_completed(self):
        store = DictationSessionStore(max_results=2, ttl_seconds=6000)
        sessions = []

        for index, ts in enumerate([5000.0, 5001.0, 5002.0], start=1):
            with self._at(ts):
                session_id = store.begin_session(suppress_paste=False, source=f"cap_{index}")
                store.mark_processing()
                store.complete_active(
                    processed_text=f"text_{index}",
                    history_entry_id=f"hist_{index}",
                    completed_at=ts,
                )
                sessions.append(session_id)

        with self._at(5003.0):
            oldest = store.get_session_result(sessions[0])
            newer_one = store.get_session_result(sessions[1])
            newest = store.get_session_result(sessions[2])

        self.assertEqual(oldest.get("state"), "not_found")
        self.assertEqual(newer_one.get("state"), "complete")
        self.assertEqual(newest.get("state"), "complete")


if __name__ == "__main__":
    unittest.main()
