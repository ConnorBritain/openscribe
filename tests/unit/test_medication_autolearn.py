import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from vocabulary.medication_autolearn import MedicationAutoLearnService
from vocabulary.medication_autolearn import set_global_medication_autolearn_service
from vocabulary.medication_error_analyzer import (
    analyze_history_incremental,
    confidence_label,
    read_history_records,
)
from vocabulary.vocabulary_api import VocabularyAPI
from vocabulary.vocabulary_manager import VocabularyManager


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.current = float(start)

    def time(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += float(seconds)


class MedicationAutoLearnServiceHarness(MedicationAutoLearnService):
    def __init__(self, *args, **kwargs):
        self.scheduled_delays = []
        super().__init__(*args, **kwargs)

    def _schedule_after(self, delay_seconds: float) -> None:
        # Avoid real timer threads in unit tests.
        self.scheduled_delays.append(float(delay_seconds))


def _write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')


class TestMedicationAnalyzerCore(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.history_path = self.test_dir / 'history.jsonl'
        self.lexicon_path = self.test_dir / 'medical_lexicon.json'
        self.user_vocab_path = self.test_dir / 'user_vocabulary.json'

        self.lexicon_path.write_text(
            json.dumps({"terms": ["mounjaro", "ozempic", "metformin"]}),
            encoding='utf-8',
        )
        self.user_vocab_path.write_text(
            json.dumps({"terms": {}}),
            encoding='utf-8',
        )

    def tearDown(self):
        set_global_medication_autolearn_service(None)
        shutil.rmtree(self.test_dir)

    def test_confidence_label_thresholds(self):
        self.assertEqual(confidence_label(0.95), 'high')
        self.assertEqual(confidence_label(0.80), 'medium')
        self.assertEqual(confidence_label(0.60), 'low')

    def test_incremental_history_offsets(self):
        _write_jsonl(
            self.history_path,
            [
                {"id": "1", "createdAt": "2026-01-01T00:00:00+00:00", "transcript": "Dose of mounjaro 5 mg"},
                {"id": "2", "createdAt": "2026-01-01T00:01:00+00:00", "transcript": "Refill of ozempic 1 mg"},
            ],
        )
        first_records, first_last_line = read_history_records(self.history_path, start_line=0)
        self.assertEqual(len(first_records), 2)
        self.assertEqual(first_last_line, 2)

        with self.history_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({
                "id": "3",
                "createdAt": "2026-01-01T00:02:00+00:00",
                "transcript": "Dose of metformin 500 mg"
            }) + '\n')

        second_records, second_last_line = read_history_records(self.history_path, start_line=2)
        self.assertEqual(len(second_records), 1)
        self.assertEqual(second_records[0].record_id, '3')
        self.assertEqual(second_last_line, 3)

    def test_candidate_extraction_from_incremental_analysis(self):
        _write_jsonl(
            self.history_path,
            [
                {
                    "id": "a1",
                    "createdAt": "2026-01-01T00:00:00+00:00",
                    "transcript": "Please refill dose of ozampic 1 mg weekly",
                },
                {
                    "id": "a2",
                    "createdAt": "2026-01-01T00:01:00+00:00",
                    "transcript": "Start mounjara 2 mg and continue",
                },
            ],
        )

        result = analyze_history_incremental(
            history_path=self.history_path,
            lexicon_path=self.lexicon_path,
            user_vocabulary_path=self.user_vocab_path,
            start_line=0,
        )

        self.assertEqual(result['scanned_records'], 2)
        self.assertEqual(result['last_processed_history_line'], 2)
        candidates = result['candidates']
        self.assertTrue(any(c['observed'] == 'ozampic' for c in candidates))


class TestMedicationAutoLearnService(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.clock = FakeClock()
        self.busy = False
        self.auto_enabled = True

        self.config_dir = self.test_dir / 'data'
        self.vocab_manager = VocabularyManager(config_dir=str(self.config_dir))

        self.state_path = self.test_dir / 'medication_autolearn_state.json'
        self.history_path = self.test_dir / 'history.jsonl'
        self.lexicon_path = self.test_dir / 'medical_lexicon.json'
        self.user_vocab_path = self.test_dir / 'user_vocabulary.json'

        self.lexicon_path.write_text(
            json.dumps({"terms": ["mounjaro", "ozempic"]}),
            encoding='utf-8',
        )
        self.user_vocab_path.write_text(
            json.dumps({"terms": {}}),
            encoding='utf-8',
        )
        _write_jsonl(self.history_path, [])

        self.service = MedicationAutoLearnServiceHarness(
            vocab_manager=self.vocab_manager,
            settings_enabled_getter=lambda: self.auto_enabled,
            busy_check=lambda: self.busy,
            state_path=str(self.state_path),
            history_path=str(self.history_path),
            lexicon_path=str(self.lexicon_path),
            user_vocabulary_path=str(self.user_vocab_path),
            time_fn=self.clock.time,
        )

    def tearDown(self):
        set_global_medication_autolearn_service(None)
        shutil.rmtree(self.test_dir)

    def test_scheduler_policy_threshold_idle_and_cooldown(self):
        self.service.state['newDictationCount'] = 4
        self.service._last_activity_at = self.clock.time() - 200
        summary = self.service.run_if_due()
        self.assertEqual(summary['runReason'], 'auto:waiting_for_more_dictations')

        self.service.state['newDictationCount'] = 5
        self.service._last_activity_at = self.clock.time() - 20
        summary = self.service.run_if_due()
        self.assertEqual(summary['runReason'], 'auto:idle_gate')

        self.service._last_activity_at = self.clock.time() - 200
        self.service.state['lastRunAt'] = datetime.fromtimestamp(
            self.clock.time(),
            tz=timezone.utc,
        ).isoformat()
        summary = self.service.run_if_due()
        self.assertEqual(summary['runReason'], 'auto:cooldown')

    def test_lock_behavior_during_concurrent_run(self):
        acquired = self.service._run_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            summary = self.service.run_now()
            self.assertIn('already in progress', summary.get('error') or '')
        finally:
            self.service._run_lock.release()

    def test_env_kill_switch_disables_service(self):
        with patch.dict(os.environ, {'CT_MEDICATION_AUTOLEARN_DISABLED': '1'}):
            disabled_service = MedicationAutoLearnServiceHarness(
                vocab_manager=self.vocab_manager,
                settings_enabled_getter=lambda: True,
                busy_check=lambda: False,
                state_path=str(self.state_path),
                history_path=str(self.history_path),
                lexicon_path=str(self.lexicon_path),
                user_vocabulary_path=str(self.user_vocab_path),
                time_fn=self.clock.time,
            )
            summary = disabled_service.run_now()
            self.assertIn('disabled by CT_MEDICATION_AUTOLEARN_DISABLED', summary.get('error') or '')

    def test_guarded_rules_high_import_medium_queue_low_ignore(self):
        analysis_payload = {
            'candidates': [
                {
                    'observed': 'mounjaroo',
                    'suggested': 'mounjaro',
                    'confidence': 'high',
                    'occurrences': 2,
                    'entry_count': 2,
                    'evidence': 'dose_of',
                    'sample_context': 'sample',
                },
                {
                    'observed': 'ozampic',
                    'suggested': 'ozempic',
                    'confidence': 'medium',
                    'occurrences': 1,
                    'entry_count': 1,
                    'evidence': 'term_plus_unit',
                    'sample_context': 'sample',
                },
                {
                    'observed': 'xyzzdrug',
                    'suggested': 'metformin',
                    'confidence': 'low',
                    'occurrences': 3,
                    'entry_count': 2,
                    'evidence': 'unknown',
                    'sample_context': 'sample',
                },
            ],
            'scanned_records': 5,
            'last_processed_history_line': 12,
        }

        with patch('vocabulary.medication_autolearn.analyze_history_incremental', return_value=analysis_payload):
            summary = self.service.run_now()

        self.assertEqual(summary['importedMappings'], 1)
        self.assertEqual(summary['queuedReviews'], 1)

        mappings = self.vocab_manager.get_medication_mappings()
        self.assertTrue(any(row['observed'] == 'mounjaroo' for row in mappings))
        self.assertFalse(any(row['observed'] == 'ozampic' for row in mappings))

        pending = self.vocab_manager.get_medication_review_queue(status_filter='pending')
        self.assertTrue(any(item['observed'] == 'ozampic' for item in pending))
        self.assertFalse(any(item['observed'] == 'xyzzdrug' for item in pending))

        state_payload = json.loads(self.state_path.read_text(encoding='utf-8'))
        self.assertEqual(state_payload['lastProcessedHistoryLine'], 12)
        self.assertIn('lastSummary', state_payload)

    def test_lifecycle_trigger_updates_state_and_runs(self):
        for _ in range(5):
            self.service.notify_dictation_completed()

        self.assertEqual(self.service.state['newDictationCount'], 5)
        self.assertGreaterEqual(len(self.service.scheduled_delays), 1)

        self.service._last_activity_at = self.clock.time() - 200
        analysis_payload = {
            'candidates': [],
            'scanned_records': 5,
            'last_processed_history_line': 5,
        }

        with patch('vocabulary.medication_autolearn.analyze_history_incremental', return_value=analysis_payload):
            summary = self.service.run_if_due()

        self.assertEqual(summary['runReason'], 'auto')
        self.assertEqual(self.service.state['newDictationCount'], 0)
        self.assertEqual(self.service.state['lastProcessedHistoryLine'], 5)

    def test_state_persistence_writes_atomically(self):
        self.service.state["newDictationCount"] = 3
        self.service._save_state()
        tmp_candidates = list(self.state_path.parent.glob(f"{self.state_path.name}.tmp.*"))
        self.assertEqual(tmp_candidates, [])
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["newDictationCount"], 3)

    def test_cooldown_uses_monotonic_time_gates(self):
        wall_clock = FakeClock(start=2_000_000.0)
        monotonic_clock = FakeClock(start=100.0)
        service = MedicationAutoLearnServiceHarness(
            vocab_manager=self.vocab_manager,
            settings_enabled_getter=lambda: True,
            busy_check=lambda: False,
            state_path=str(self.state_path),
            history_path=str(self.history_path),
            lexicon_path=str(self.lexicon_path),
            user_vocabulary_path=str(self.user_vocab_path),
            time_fn=wall_clock.time,
            monotonic_fn=monotonic_clock.time,
        )
        service.state["newDictationCount"] = 5
        service._last_activity_at = monotonic_clock.time() - 200
        service.state["lastRunAt"] = datetime.fromtimestamp(
            wall_clock.time(),
            tz=timezone.utc,
        ).isoformat()
        first = service.run_if_due()
        self.assertEqual(first["runReason"], "auto:cooldown")

        # Move wall time backwards; cooldown should still use monotonic elapsed time.
        wall_clock.advance(-86_400)
        monotonic_clock.advance(100)
        second = service.run_if_due()
        self.assertEqual(second["runReason"], "auto:cooldown")


class TestMedicationAutoLearnAPI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.vocab_manager = VocabularyManager(config_dir=str(self.test_dir / 'data'))

        self.state_path = self.test_dir / 'medication_autolearn_state.json'
        self.history_path = self.test_dir / 'history.jsonl'
        self.lexicon_path = self.test_dir / 'medical_lexicon.json'
        self.user_vocab_path = self.test_dir / 'user_vocabulary.json'

        self.lexicon_path.write_text(json.dumps({"terms": ["mounjaro"]}), encoding='utf-8')
        self.user_vocab_path.write_text(json.dumps({"terms": {}}), encoding='utf-8')
        _write_jsonl(self.history_path, [])

        self.service = MedicationAutoLearnServiceHarness(
            vocab_manager=self.vocab_manager,
            settings_enabled_getter=lambda: True,
            busy_check=lambda: False,
            state_path=str(self.state_path),
            history_path=str(self.history_path),
            lexicon_path=str(self.lexicon_path),
            user_vocabulary_path=str(self.user_vocab_path),
        )

        self.api = VocabularyAPI()
        self.api.vocab_manager = self.vocab_manager
        self.api.set_medication_autolearn_service(self.service)

    def tearDown(self):
        set_global_medication_autolearn_service(None)
        shutil.rmtree(self.test_dir)

    def test_get_medication_autolearn_status(self):
        result = self.api.get_medication_autolearn_status()
        self.assertTrue(result['success'])
        self.assertIn('status', result)
        self.assertIn('lastSummary', result)

    def test_get_medication_autolearn_status_without_service(self):
        set_global_medication_autolearn_service(None)
        isolated_api = VocabularyAPI()
        isolated_api.vocab_manager = self.vocab_manager
        isolated_api.set_medication_autolearn_service(None)
        result = isolated_api.get_medication_autolearn_status()
        self.assertFalse(result['success'])
        self.assertIn('not initialized', result['error'])

    def test_run_medication_autolearn_now(self):
        analysis_payload = {
            'candidates': [],
            'scanned_records': 3,
            'last_processed_history_line': 3,
        }
        with patch('vocabulary.medication_autolearn.analyze_history_incremental', return_value=analysis_payload):
            result = self.api.run_medication_autolearn_now()

        self.assertTrue(result['success'])
        self.assertEqual(result['summary']['scannedRecords'], 3)
        self.assertEqual(result['summary']['runReason'], 'manual')


class TestMedicationAutoLearnFrontendWiring(unittest.TestCase):
    def test_settings_ui_contains_autolearn_controls_and_badge(self):
        repo_root = Path(__file__).resolve().parents[2]
        html_path = repo_root / 'frontend' / 'settings' / 'settings.html'
        renderer_path = repo_root / 'frontend' / 'settings' / 'settings_renderer.js'

        html_text = html_path.read_text(encoding='utf-8')
        renderer_text = renderer_path.read_text(encoding='utf-8')

        self.assertIn('id="nav-vocabulary-badge"', html_text)
        self.assertIn('id="med-autolearn-toggle"', html_text)
        self.assertIn('id="med-autolearn-run-now"', html_text)
        self.assertIn('id="med-autolearn-last-summary"', html_text)

        self.assertIn('get_medication_autolearn_status', renderer_text)
        self.assertIn('run_medication_autolearn_now', renderer_text)


if __name__ == '__main__':
    unittest.main()
