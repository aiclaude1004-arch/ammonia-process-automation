"""Refresh integrity hashes only after intentionally reviewing source changes."""
from pathlib import Path
import hashlib, json
root=Path(__file__).resolve().parents[1]
ignored={'.git','__pycache__','.venv','outputs','build','dist'}
files=[p for p in root.rglob('*') if p.is_file() and not ignored.intersection(p.relative_to(root).parts)
       and p.name!='snapshot_sha256.json' and not any(x.endswith('.egg-info') for x in p.parts)]
hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
(root/'provenance/snapshot_sha256.json').write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
print(f'Recorded {len(hashes)} file hashes.')
