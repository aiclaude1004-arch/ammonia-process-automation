"""Capture a pinned C0295 source-only preparation child; never start Aspen."""
import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pin(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('Each expected SHA256 must be an independently supplied lowercase digest')
    return value


def strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def write_raw(path, value):
    with path.open('xb') as handle:
        view = memoryview(value)
        while view:
            written = handle.write(view)
            if type(written) is not int or written <= 0 or written > len(view):
                raise OSError('Incomplete evidence write')
            view = view[written:]
        handle.flush()
        os.fsync(handle.fileno())
    if path.read_bytes() != value:
        raise OSError('Persisted evidence differs from captured bytes')


def verify_rows(raw, expected_manifest, expected_rows):
    if not raw.endswith(b"\n"):
        raise ValueError("Final complete line terminator required")
    framed = raw.split(b'\n')
    if len(framed) != 101 or framed[-1] != b'':
        raise ValueError('Exactly 100 LF-delimited JSON lines are required')
    rows = framed[:-1]
    seen = set()
    for index, line_bytes in enumerate(rows):
        line = line_bytes.decode('utf-8', errors='strict')
        result = strict(line)
        if type(result) is not dict or result.get('schema') != 'c0295.source_prepare.v1':
            raise ValueError('Wrong source preparation schema')
        required = {'schema', 'case_id', 'row', 'phase', 'bridge_manifest_sha256',
                    'adapter_peer_selected', 'source_only', 'ready_for_native_execution',
                    'future_required', 'COM_calls', 'host_queries', 'leases', 'grants_issued',
                    'native_approved', 'scientific_approval'}
        if set(result) != required:
            raise ValueError('Unexpected or missing source result fields')
        row = result.get('row')
        if (json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)
                != json.dumps(expected_rows[index], sort_keys=True, separators=(',', ':'), allow_nan=False)):
            raise ValueError('Source row differs from the authenticated ordered plan')
        if (type(row) is not dict or row.get('case_id') != 'C0295'
                or type(row.get('ordinal')) is not int or row['ordinal'] != index
                or type(row.get('point_id')) is not str or row['point_id'] in seen):
            raise ValueError('Wrong case, ordinal, or duplicated point ID')
        seen.add(row['point_id'])
        if (result.get('case_id') != 'C0295' or result.get('phase') != 'Primary'
                or result.get('bridge_manifest_sha256') != expected_manifest
                or result.get('source_only') is not True
                or result.get('adapter_peer_selected') is not False
                or result.get('ready_for_native_execution') is not False
                or result.get('native_approved') is not False
                or result.get('scientific_approval') is not False):
            raise ValueError('Source-only, manifest, phase, or approval mismatch')
        if result.get('future_required') != ["Exact independent whole source/root peer", "Genuine own current runtime/import admission", "Finite original single-phase parent authority", "Primary full science/history/exit closure before distinct Fresh", "Own KAL inventory/cold design specification/scientific qualification remains required"]:
            raise ValueError('Future source-only requirements differ')
        for key in ('COM_calls', 'host_queries', 'leases', 'grants_issued'):
            if type(result.get(key)) is not int or result[key] != 0:
                raise ValueError('Invalid side-effect counter: ' + key)
    return len(rows)


def validate_paths(python, tool, manifest_file, output):
    workspace = Path(__file__).resolve().parent.parent
    expected = (
        workspace / 'Replay_Environment' / 'Scripts' / 'python.exe',
        workspace / 'C0295_source_prepare_batch_v4_candidate_20261102_v1' / 'prepare_batch.py',
        workspace / 'Paper_Data_20260928' / 'analysis_consistent_v1' / 'native_resume_20261030_v1'
            / 'sofc_execution_sol' / 'C0295_native_bridge_v3' / 'Code_Manifest.json',
    )
    for candidate, required in zip((python, tool, manifest_file), expected):
        text = str(candidate).replace('/', chr(92))
        if (text.startswith((chr(92) * 2, chr(92) + '??' + chr(92)))
                or ':' in ntpath.splitdrive(text)[1]
                or ntpath.normcase(ntpath.abspath(text)) != ntpath.normcase(ntpath.abspath(str(required)))):
            raise ValueError('Only exact C0295 source paths are allowed before read')
    output_text = str(output).replace('/', chr(92))
    if (output_text.startswith((chr(92) * 2, chr(92) + '??' + chr(92)))
            or ':' in ntpath.splitdrive(output_text)[1]):
        raise ValueError('Output device, UNC and ADS paths are forbidden')
    components = output_text.split(chr(92))
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN' + chr(36), 'CONOUT' + chr(36)}
    reserved.update('COM' + str(i) for i in range(1, 10))
    reserved.update('LPT' + str(i) for i in range(1, 10))
    reserved.update(prefix + digit for prefix in ('COM', 'LPT') for digit in ('¹', '²', '³'))
    for part in components:
        if not part or part.endswith(':'):
            continue
        cleaned = part.rstrip(' .')
        stem = cleaned.split('.', 1)[0].upper()
        if (cleaned != part or stem in reserved or cleaned.lower().startswith('stop')
                or cleaned.lower().endswith('.lock')):
            raise ValueError('Output STOP, lock, or reserved device path is forbidden')
    allowed = (workspace / 'supercase' / 'C0295' / '04_검증').resolve(strict=True)
    parent = output.parent.resolve(strict=True)
    try:
        contained = os.path.commonpath((str(allowed), str(parent))) == str(allowed)
    except ValueError:
        contained = False
    if not contained:
        raise ValueError('Output must be inside the C0295 validation directory')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('python', 'python-sha256', 'tool', 'tool-sha256', 'manifest-file', 'manifest-sha256', 'output'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=120)
    args = parser.parse_args()
    python_hash, tool_hash, manifest_hash = map(pin,
        (args.python_sha256, args.tool_sha256, args.manifest_sha256))
    if not 1 <= args.timeout_seconds <= 600:
        raise ValueError('Timeout must be between 1 and 600 seconds')
    python = Path(args.python)
    tool = Path(args.tool)
    output = Path(args.output)
    manifest_file = Path(args.manifest_file)
    if not all(path.is_absolute() for path in (python, tool, manifest_file, output)):
        raise ValueError('Python, tool, and output paths must be absolute')
    validate_paths(python, tool, manifest_file, output)
    python_raw, tool_raw = python.read_bytes(), tool.read_bytes()
    if digest(python_raw) != python_hash or digest(tool_raw) != tool_hash:
        raise ValueError('Caller-pinned Python or tool bytes differ')
    manifest_raw = manifest_file.read_bytes()
    if digest(manifest_raw) != manifest_hash:
        raise ValueError('Caller-pinned manifest bytes differ')
    manifest = strict(manifest_raw)
    index_path = (manifest_file.parent / 'Saved_Row_Index.json').resolve()
    expected_index_hash = manifest['files'].get(str(index_path))
    if type(expected_index_hash) is not str or re.fullmatch(r'[0-9a-f]{64}', expected_index_hash) is None:
        raise ValueError('Authenticated manifest does not pin the ordered row index')
    index_raw = index_path.read_bytes()
    if digest(index_raw) != expected_index_hash:
        raise ValueError('Authenticated ordered row index differs')
    index = strict(index_raw)
    expected_rows = index['rows']
    if (index.get('case_id') != 'C0295' or type(expected_rows) is not list or len(expected_rows) != 100):
        raise ValueError('Exact C0295 saved 100-row plan required')
    output.mkdir(parents=False, exist_ok=False)
    bootstrap = (
        'import hashlib,sys\n'
        'expected=sys.argv.pop(1)\n'
        'source=sys.stdin.buffer.read()\n'
        'if hashlib.sha256(source).hexdigest()!=expected: raise ValueError("Tool bytes differ")\n'
        'exec(compile(source,"<pinned-c0295-batch>","exec",optimize=0),'
        '{"__name__":"__main__"})\n'
    )
    command = [str(python), '-I', '-S', '-B', '-X', 'utf8', '-c', bootstrap,
               tool_hash, '--manifest-sha256', manifest_hash]
    started = time.perf_counter_ns()
    timed_out = False
    try:
        child = subprocess.run(command, input=tool_raw, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=args.timeout_seconds, check=False)
        stdout, stderr, returncode = child.stdout, child.stderr, child.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr, returncode = exc.stdout or b'', exc.stderr or b'', None
    elapsed = time.perf_counter_ns() - started
    write_raw(output / 'Child.stdout', stdout)
    write_raw(output / 'Child.stderr', stderr)
    problem = None
    count = None
    if timed_out or returncode != 0:
        problem = 'Timed out' if timed_out else 'Child exit was not zero'
    else:
        try:
            if digest(manifest_file.read_bytes()) != manifest_hash or digest(index_path.read_bytes()) != expected_index_hash:
                raise ValueError("Authenticated manifest or row index drifted after child")
            count = verify_rows(stdout, manifest_hash, expected_rows)
        except Exception as exc:
            problem = type(exc).__name__ + ': ' + str(exc)
    if (output / 'Child.stdout').read_bytes() != stdout or (output / 'Child.stderr').read_bytes() != stderr:
        problem = 'Persisted raw changed before receipt publication'
        count = None
    receipt = {
        'schema': 'c0295.source_prepare_capture.v1',
        'status': 'SOURCE_ONLY_PREPARATION_COMPLETE' if problem is None else 'BLOCKED',
        'problem': problem,
        'child_exit_code': returncode,
        'timed_out': timed_out,
        'child_wall_ns': elapsed,
        'captured_stdout_sha256': digest(stdout),
        'captured_stderr_sha256': digest(stderr),
        'captured_stdout_bytes': len(stdout),
        'captured_stderr_bytes': len(stderr),
        'validated_rows': count,
        'caller_expected_manifest_sha256': manifest_hash,
        'authenticated_row_index_sha256': expected_index_hash,
        'caller_expected_tool_sha256': tool_hash,
        'caller_expected_python_sha256': python_hash,
        'source_only': True,
        'runtime_approved': False,
        'native_approved': False,
        'scientific_approval': False,
        'limitations': ['Caller must authenticate this launcher and all supplied pins.',
                        'Interpreter path could change between hash and OS launch.',
                        'Filesystem reparse changes may race path validation.',
                        'Capture sink failure or process termination can prevent a complete receipt.',
                        'Consumers must verify launcher exit and raw digests after publication.',
                        'Raw files may change after the final readback.',
                        'This is not parent binding or Aspen execution.'],
    }
    pending = output / 'Receipt.pending'
    write_raw(pending, (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    if os.name != 'nt':
        raise OSError('No-overwrite receipt publication requires Windows')
    os.rename(pending, output / 'Receipt.json')
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if problem is None else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'blocked': True, 'reason': type(exc).__name__ + ': ' + str(exc),
                          'native_approved': False, 'scientific_approval': False},
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
