import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scrum_state import StateError, read_state, write_state
import scrum_state


class StateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sync-state.json"
        self.target = {"provider": "jira-cloud", "base_url": "https://example.test", "project": "APP"}

    def test_roundtrip_and_revision_conflict(self):
        saved = write_state(self.path, self.target, {"items": {"story-1": "APP-1"}}, 0)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(read_state(self.path, self.target), saved)
        with self.assertRaises(StateError):
            write_state(self.path, self.target, {}, 0)
        self.assertEqual(read_state(self.path, self.target), saved)

    def test_wrong_target_or_lock_blocks_writes(self):
        write_state(self.path, self.target, {}, 0)
        with self.assertRaises(StateError):
            read_state(self.path, {**self.target, "project": "OTHER"})
        lock = self.path.with_name(self.path.name + ".lock")
        lock.mkdir()
        with self.assertRaises(StateError):
            write_state(self.path, self.target, {}, 1)
        lock.rmdir()

    def test_failure_before_replace_preserves_existing_file(self):
        write_state(self.path, self.target, {"items": {"a": 1}}, 0)
        original = self.path.read_bytes()
        with patch("scrum_state.os.replace", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                write_state(self.path, self.target, {}, 1)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.path.with_name(self.path.name + ".lock").exists())

    def test_credential_fields_and_known_values_are_rejected(self):
        cases = [
            {"GIT_PAT": "fake-secret"},
            {"items": {"one": {"GIT_PAT": "fake-secret"}}},
            {"verification": {"nested": [{"Authorization": "Bearer fake-secret"}]}},
            {"resources": {"note": "fake-secret"}},
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(StateError):
                write_state(self.path, self.target, data, 0, secrets=["fake-secret"])
        self.assertFalse(self.path.exists())

    def test_legacy_state_with_credentials_is_not_returned(self):
        write_state(self.path, self.target, {}, 0)
        raw = json.loads(self.path.read_text())
        raw["data"] = {"items": {"one": {"access_token": "fake-secret"}}}
        self.path.write_text(json.dumps(raw))
        with self.assertRaises(StateError):
            read_state(self.path, self.target)

    def test_successful_cli_write_does_not_echo_state_data(self):
        target_file = self.path.parent / "target.json"
        target_file.write_text(json.dumps(self.target))
        data_file = self.path.parent / "data.json"
        data_file.write_text(json.dumps({"items": {"one": {"note": "private-work-description"}}}))
        argv = ["scrum_state.py", "write", "--file", str(self.path), "--target-file", str(target_file),
                "--data-file", str(data_file), "--expected-revision", "0"]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
            self.assertEqual(scrum_state.main(), 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["revision"], 1)
        self.assertNotIn("data", summary)
        self.assertNotIn("private-work-description", output.getvalue())

    def test_cli_checks_configured_secret_values_without_echoing_them(self):
        target_file = self.path.parent / "target.json"
        target_file.write_text(json.dumps(self.target))
        data_file = self.path.parent / "data.json"
        data_file.write_text(json.dumps({"items": {"one": {"note": "fake-secret"}}}))
        env_file = self.path.parent / ".env"
        env_file.write_text("GIT_PAT=fake-secret\n")
        argv = ["scrum_state.py", "write", "--file", str(self.path), "--target-file", str(target_file),
                "--data-file", str(data_file), "--expected-revision", "0", "--env-file", str(env_file)]
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(scrum_state.main(), 1)
        self.assertNotIn("fake-secret", output.getvalue() + errors.getvalue())
        self.assertFalse(self.path.exists())

    def test_unknown_schema_and_sections_are_rejected(self):
        with self.assertRaises(StateError):
            write_state(self.path, self.target, {"configuration": {}}, 0)
        write_state(self.path, self.target, {}, 0)
        raw = json.loads(self.path.read_text())
        raw["schema_version"] = True
        self.path.write_text(json.dumps(raw))
        with self.assertRaises(StateError):
            read_state(self.path, self.target)


if __name__ == "__main__":
    unittest.main()
