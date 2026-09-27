"""Verify the unchanged raw hardware attachment and host source files."""
import hashlib
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'inputs/HARDWARE-SHA256.json').read_text())
for relative, expected in manifest.items():
    path = root / relative
    assert path.is_file(), f'Missing hardware file: {relative}'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f'Changed hardware file: {relative}'
print(f'PASS: {len(manifest)} original hardware files verified.')
