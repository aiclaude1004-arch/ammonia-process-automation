from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aspen_automation import LaunchOptions, validate_backup
import aspen_automation.session as session_module


class SessionPreflightTest(unittest.TestCase):
    def test_initial_session_is_visible_and_shows_dialogs(self):
        options = LaunchOptions()
        self.assertTrue(options.visible)
        self.assertFalse(options.suppress_dialogs)

    def test_valid_ascii_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "test_case.bkp"
            backup.touch()
            self.assertEqual(validate_backup(backup), backup.resolve())

    def test_non_ascii_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "테스트.bkp"
            backup.touch()
            with self.assertRaises(ValueError):
                validate_backup(backup)

    def test_parallel_launch_is_disabled_by_default(self):
        self.assertFalse(LaunchOptions().allow_parallel_aspen)

    def test_running_aspen_processes_filters_tasklist_rows(self):
        original_run = session_module.subprocess.run

        class Result:
            stdout = '"AspenPlus.exe","1234","Console","1","100 K"\n"notepad.exe","99","Console","1","1 K"\n"apmain.exe","5678","Console","1","100 K"'

        try:
            session_module.subprocess.run = lambda *args, **kwargs: Result()
            self.assertEqual(len(session_module.running_aspen_processes()), 2)
        finally:
            session_module.subprocess.run = original_run


if __name__ == "__main__":
    unittest.main()
