"""Synthetic tests for captured child failures; does not launch Aspen or a child."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PYTHON = ROOT / 'Replay_Environment' / 'Scripts' / 'python.exe'
TOOL = ROOT / 'C0295_source_prepare_batch_v4_candidate_20261102_v1' / 'prepare_batch.py'
ACTUAL = ROOT / 'supercase' / 'C0295' / '04_검증' / 'C0295_source_capture_20261102_v1' / 'reviewed_manifest' / 'Child.stdout'
MANIFEST = '28204f4a4bccf2d9e128eb5d85b00adc268a3fb0318bc4e92cfb7f12c809f6e0'
spec = importlib.util.spec_from_file_location('capture_candidate_test', HERE / 'capture_prepare.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'supercase' / 'C0295' / '04_검증', prefix='fixture_capture_v3_')
        self.output = Path(self.tmp.name) / 'capture'
        self.addCleanup(self.tmp.cleanup)
        self.args = ['capture_prepare.py', '--python', str(PYTHON),
                     '--python-sha256', hashlib.sha256(PYTHON.read_bytes()).hexdigest(),
                     '--tool', str(TOOL), '--tool-sha256', hashlib.sha256(TOOL.read_bytes()).hexdigest(),
                     '--manifest-file', str(ROOT / 'Paper_Data_20260928' / 'analysis_consistent_v1' / 'native_resume_20261030_v1' / 'sofc_execution_sol' / 'C0295_native_bridge_v3' / 'Code_Manifest.json'), '--manifest-sha256', MANIFEST, '--output', str(self.output)]

    def run_fake(self, fake):
        with patch.object(sys, 'argv', self.args), patch.object(module.subprocess, 'run', side_effect=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                code = module.main()
        return code, json.loads((self.output / 'Receipt.json').read_bytes())

    def test_nonzero_child_preserves_partial_raw_bytes(self):
        def fake(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 7, b'partial\xff', b'err\x00\xfe')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['child_exit_code'], 7)
        self.assertEqual((self.output / 'Child.stdout').read_bytes(), b'partial\xff')
        self.assertEqual((self.output / 'Child.stderr').read_bytes(), b'err\x00\xfe')
        self.assertEqual(result['captured_stdout_sha256'], hashlib.sha256(b'partial\xff').hexdigest())

    def test_zero_exit_with_partial_output_is_blocked(self):
        def fake(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, ACTUAL.read_bytes().splitlines()[0] + b'\n', b'')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIsNone(result['validated_rows'])

    def test_timeout_preserves_reported_partial_bytes(self):
        def fake(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 1, output=b'timeout\xff', stderr=b'failure\xfe')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertTrue(result['timed_out'])
        self.assertIsNone(result['child_exit_code'])
        self.assertEqual((self.output / 'Child.stdout').read_bytes(), b'timeout\xff')
        self.assertEqual((self.output / 'Child.stderr').read_bytes(), b'failure\xfe')

    def test_zero_exit_with_all_saved_rows_is_source_only(self):
        def fake(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, ACTUAL.read_bytes(), b'timing')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 0)
        self.assertEqual(result['validated_rows'], 100)
        self.assertIs(result['native_approved'], False)
        self.assertIs(result['scientific_approval'], False)

    def test_duplicate_row_is_blocked(self):
        rows = ACTUAL.read_bytes().splitlines()
        rows[-1] = rows[0]
        def fake(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, b'\n'.join(rows) + b'\n', b'')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')


    def test_missing_final_newline_is_blocked(self):
        def fake(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, ACTUAL.read_bytes().rstrip(b'\r\n'), b'')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')

    def test_swapped_point_ids_are_blocked(self):
        rows = [json.loads(line) for line in ACTUAL.read_bytes().splitlines()]
        rows[0]['row']['point_id'], rows[1]['row']['point_id'] = rows[1]['row']['point_id'], rows[0]['row']['point_id']
        raw = b'\n'.join(json.dumps(row, ensure_ascii=False).encode('utf-8') for row in rows) + b'\n'
        def fake(*args, **kwargs): return subprocess.CompletedProcess(args[0], 0, raw, b'')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')

    def test_extra_approval_field_is_blocked(self):
        rows = [json.loads(line) for line in ACTUAL.read_bytes().splitlines()]
        rows[0]['approved_for_production'] = True
        raw = b'\n'.join(json.dumps(row, ensure_ascii=False).encode('utf-8') for row in rows) + b'\n'
        def fake(*args, **kwargs): return subprocess.CompletedProcess(args[0], 0, raw, b'')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')

    def test_future_requirements_change_is_blocked(self):
        rows = [json.loads(line) for line in ACTUAL.read_bytes().splitlines()]
        rows[0]['future_required'] = []
        raw = b'\n'.join(json.dumps(row, ensure_ascii=False).encode('utf-8') for row in rows) + b'\n'
        def fake(*args, **kwargs): return subprocess.CompletedProcess(args[0], 0, raw, b'')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')

    def test_silent_short_write_is_detected(self):
        class FakeHandle:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def write(self, value): return len(value)
            def flush(self): pass
            def fileno(self): return 1
        class FakePath:
            def open(self, mode): return FakeHandle()
            def read_bytes(self): return b'partial'
        with patch.object(module.os, 'fsync', return_value=None):
            with self.assertRaises(OSError): module.write_raw(FakePath(), b'complete')


    def test_untrusted_input_paths_rejected_before_reads(self):
        manifest = ROOT / 'Paper_Data_20260928' / 'analysis_consistent_v1' / 'native_resume_20261030_v1' / 'sofc_execution_sol' / 'C0295_native_bridge_v3' / 'Code_Manifest.json'
        fake_stop = ROOT / 'STOP.json'
        for paths in ((fake_stop, TOOL, manifest), (PYTHON, fake_stop, manifest), (PYTHON, TOOL, fake_stop)):
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Unexpected file read')):
                with self.assertRaises(ValueError): module.validate_paths(*paths, self.output)

    def test_output_outside_case_and_lock_names_rejected(self):
        manifest = ROOT / 'Paper_Data_20260928' / 'analysis_consistent_v1' / 'native_resume_20261030_v1' / 'sofc_execution_sol' / 'C0295_native_bridge_v3' / 'Code_Manifest.json'
        for bad in (ROOT / 'other_output', self.output.parent / 'ACTIVE_ASPEN.lock', self.output.parent / 'STOP.json'):
            with self.assertRaises(ValueError): module.validate_paths(PYTHON, TOOL, manifest, bad)


    def test_non_lf_line_separators_are_blocked(self):
        rows = ACTUAL.read_bytes().decode('utf-8').splitlines()
        raw = ('\u2028'.join(rows) + '\n').encode('utf-8')
        def fake(*args, **kwargs): return subprocess.CompletedProcess(args[0], 0, raw, b'')
        code, result = self.run_fake(fake)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'BLOCKED')

    def test_receipt_fsync_failure_does_not_publish_complete_receipt(self):
        def fake(*args, **kwargs): return subprocess.CompletedProcess(args[0], 0, ACTUAL.read_bytes(), b'')
        calls = []
        def fsync(fd):
            calls.append(fd)
            if len(calls) == 3: raise OSError('synthetic receipt fsync failure')
        with patch.object(sys, 'argv', self.args), patch.object(module.subprocess, 'run', side_effect=fake), patch.object(module.os, 'fsync', side_effect=fsync):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError): module.main()
        self.assertFalse((self.output / 'Receipt.json').exists())
        self.assertTrue((self.output / 'Receipt.pending').exists())


    def test_ambiguous_stop_and_windows_device_names_rejected_before_resolve(self):
        manifest = ROOT / 'Paper_Data_20260928' / 'analysis_consistent_v1' / 'native_resume_20261030_v1' / 'sofc_execution_sol' / 'C0295_native_bridge_v3' / 'Code_Manifest.json'
        original_resolve = Path.resolve
        for name in ('STOP', 'STOP.txt', 'stopper', 'NUL', 'nul.txt', 'CON', 'PRN.log', 'COM1.txt', 'LPT9', 'COM¹', 'COM².txt', 'COM³', 'LPT¹.txt', 'LPT²', 'LPT³.txt', 'name. ', 'ACTIVE_ASPEN.lock'):
            bad = self.output.parent / name
            def guarded_resolve(path, *args, **kwargs):
                if path == bad or path == bad.parent / name:
                    raise AssertionError('Forbidden synthetic target resolved')
                return original_resolve(path, *args, **kwargs)
            with patch.object(Path, 'resolve', guarded_resolve):
                with self.assertRaises(ValueError): module.validate_paths(PYTHON, TOOL, manifest, bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
