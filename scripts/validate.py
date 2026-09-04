#!/usr/bin/env python3
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
manifest = ET.parse(root / 'default.xml').getroot()
lock = json.loads((root / 'upstream.json').read_text())
projects = manifest.findall('project')
assert len(projects) >= 60
for project in projects:
    assert re.fullmatch('[0-9a-f]{40}', project.attrib['revision']), project.attrib
qemu = next(project for project in projects if project.attrib['path'] == 'external/qemu')
assert qemu.attrib['revision'] == lock['qemu_revision']
assert manifest.find('remote').attrib['fetch'] == 'https://android.googlesource.com'
assert set(lock['targets']) == {'linux-x86_64', 'windows-x86_64', 'darwin-x86_64', 'darwin-aarch64'}
print(f'Validated {len(projects)} pinned source projects and four engine targets')
