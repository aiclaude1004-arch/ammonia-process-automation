"""Check source integrity and syntax without importing or launching Aspen."""
from pathlib import Path
import ast, hashlib, json

def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/'provenance/snapshot_sha256.json').read_text(encoding='utf-8'))
    errors = []
    for name, expected in manifest.items():
        p = root/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            errors.append('Missing or changed: '+name)
    count = 0
    for folder in ['src', 'scripts', 'tests', 'reproduction']:
        for p in (root/folder).rglob('*.py'):
            ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))
            count += 1
    if errors: raise SystemExit('\n'.join(errors))
    print(f'Integrity OK: {len(manifest)} files; syntax OK: {count} Python files; Aspen not executed.')

if __name__ == '__main__': main()
