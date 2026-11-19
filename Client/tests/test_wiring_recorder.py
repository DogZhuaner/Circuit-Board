"""Run with python -m unittest discover -s Client/tests from the repository root."""
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from script.wiring_recorder import WiringRecorder


class WiringRecorderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "history.sqlite3"
        self.store = WiringRecorder(self.path)
        self.recording_id = self.store.begin({"student_no": "demo"}, [["A", "B"]], 10)

    def test_shuffle_only_new_batch_and_freeze_on_read(self):
        with patch("script.wiring_recorder.random.shuffle", side_effect=lambda changes: changes.reverse()):
            first = self.store.append_snapshot(self.recording_id, [["A", "B"], ["C", "D"], ["E", "F"]], 30)
            self.assertEqual([event["terminals"] for event in first], [["E", "F"], ["C", "D"]])
            self.store.append_snapshot(self.recording_id, [["E", "F"]], 10)
        exported = self.store.read(self.recording_id)
        self.assertEqual(exported["events"][:2], first)
        self.assertEqual(exported, self.store.read(self.recording_id))
        self.assertEqual([event["seq"] for event in exported["events"]], [1, 2, 3, 4])
        state = {tuple(pair) for pair in exported["initial_state"]["pairs"]}
        for event in exported["events"]:
            pair = tuple(event["terminals"])
            if event["operation"] == "add":
                state.add(pair)
            else:
                state.remove(pair)
        self.assertEqual(state, {tuple(pair) for pair in exported["latest_state"]["pairs"]})

    def test_remove_readd_and_no_change(self):
        self.store.append_snapshot(self.recording_id, [], 0)
        self.store.append_snapshot(self.recording_id, [["B", "A"], ["A", "B"]], 10)
        self.store.append_snapshot(self.recording_id, [["A", "B"]], 10)
        result = self.store.read(self.recording_id)
        self.assertEqual([event["operation"] for event in result["events"]], ["remove", "add"])
        self.assertEqual(result["last_batch"], 3)
        self.assertEqual(result["batches"][-1]["event_count"], 0)

    def test_incremental_pagination_within_batch(self):
        self.store.append_snapshot(self.recording_id, [["C", "D"], ["E", "F"]], 20)
        first = self.store.read(self.recording_id, limit=1)
        second = self.store.read(self.recording_id, first["next_after_seq"], limit=2)
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual([event["seq"] for event in first["events"] + second["events"]], [1, 2, 3])

    def test_restart_preserves_events_and_marks_interrupted(self):
        self.store.append_snapshot(self.recording_id, [], 0)
        before = self.store.read(self.recording_id)
        recovered = WiringRecorder(self.path, recover=True)
        after = recovered.read(self.recording_id)
        self.assertEqual(before["events"], after["events"])
        self.assertEqual(after["status"], "interrupted")
        with self.assertRaises(ValueError):
            recovered.append_snapshot(self.recording_id, [], 0)
        new_id = recovered.begin({}, [], 0)
        self.assertNotEqual(new_id, self.recording_id)

    def test_failed_write_rolls_back_whole_batch(self):
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
        with self.assertRaises(Exception):
            self.store.append_snapshot(self.recording_id, [], 0)
        result = self.store.read(self.recording_id)
        self.assertEqual(result["last_seq"], 0)
        self.assertEqual(result["last_batch"], 0)
        self.assertEqual(result["latest_state"]["pairs"], [["A", "B"]])

    def test_concurrent_duplicate_snapshots_do_not_duplicate_events(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.store.append_snapshot(self.recording_id, [], 0), range(8)))
        self.assertEqual(len(self.store.read(self.recording_id)["events"]), 1)

    def test_finished_recording_and_second_session_are_independent(self):
        self.store.finish(self.recording_id)
        self.store.finish(self.recording_id)
        with self.assertRaises(ValueError):
            self.store.append_snapshot(self.recording_id, [], 0)
        second = self.store.begin({}, [], 0)
        self.store.append_snapshot(second, [["X", "Y"]], 5)
        self.assertEqual(self.store.read(self.recording_id)["last_seq"], 0)
        self.assertEqual(self.store.read(second)["last_seq"], 1)
        self.assertEqual(len(self.store.list_recordings()), 2)

    def test_mixed_changes_replay_in_persisted_order(self):
        with patch("script.wiring_recorder.random.shuffle", side_effect=lambda changes: changes.reverse()):
            events = self.store.append_snapshot(self.recording_id, [["C", "D"], ["E", "F"]], 20)
        self.assertEqual(events[0]["operation"], "remove")
        state = {("A", "B")}
        for event in events:
            pair = tuple(event["terminals"])
            if event["operation"] == "add":
                state.add(pair)
            else:
                state.remove(pair)
        self.assertEqual(state, {("C", "D"), ("E", "F")})

    def test_invalid_pair_does_not_change_recording(self):
        with self.assertRaises(ValueError):
            self.store.append_snapshot(self.recording_id, [["A", "A"]], 0)
        self.assertEqual(self.store.read(self.recording_id)["last_batch"], 0)

    def test_missing_recording(self):
        with self.assertRaises(KeyError):
            self.store.read("missing")


if __name__ == "__main__":
    unittest.main()
