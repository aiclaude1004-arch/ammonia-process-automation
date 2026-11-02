"""Atomic JSON publication with bounded Windows sharing-violation retries."""
import json
import os
import time
from pathlib import Path


def write_json(path, data, *, attempts=30):
    path = Path(path)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(attempts):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(min(.02 * (attempt + 1), .2))
