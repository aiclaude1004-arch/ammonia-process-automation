from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ammonia_optimizer.interactive_aspen import LaunchOptions, validate_automation_backup


class InteractiveAspenPreflightTest(unittest.TestCase):
    def test_first_launch_is_visible_with_dialogs(self):
        options = LaunchOptions()
        self.assertTrue(options.visible)
        self.assertFalse(options.suppress_dialogs)

    def test_ascii_backup_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "case.bkp"
            backup.touch()
            self.assertEqual(validate_automation_backup(backup), backup.resolve())

    def test_non_ascii_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "암모니아.bkp"
            backup.touch()
            with self.assertRaises(ValueError):
                validate_automation_backup(backup)


if __name__ == "__main__":
    unittest.main()
