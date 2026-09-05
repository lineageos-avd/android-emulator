#!/usr/bin/env python3
"""Apply only reviewed, byte-verified recipe patches to the pinned source tree."""
import hashlib
from pathlib import Path
import platform
import subprocess
import tempfile
import os

ROOT = Path(__file__).resolve().parents[1]


def describe_patches(host=None):
    host = host or platform.system().lower()
    paths = [*sorted((ROOT / 'patches/common').glob('*.patch')), *sorted((ROOT / 'patches' / host).glob('*.patch'))]
    return [{'file': path.relative_to(ROOT).as_posix(), 'project': 'external/qemu',
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in paths]


def apply_patches(source):
    qemu = Path(source) / 'external/qemu'
    patches = describe_patches()
    # Build the expected index separately so unrelated edits are never reset.
    with tempfile.TemporaryDirectory(prefix='hub-patch-index-') as temporary:
        env = os.environ | {'GIT_INDEX_FILE': str(Path(temporary) / 'index')}
        subprocess.run(['git', '-C', str(qemu), 'read-tree', 'HEAD'], env=env, check=True)
        for patch in patches:
            subprocess.run(['git', '-C', str(qemu), 'apply', '--cached', str(ROOT / patch['file'])], env=env, check=True)
        expected = subprocess.check_output(['git', '-C', str(qemu), 'diff', '--cached', '--binary', 'HEAD'], env=env)
    current = subprocess.check_output(['git', '-C', str(qemu), 'diff', '--binary', 'HEAD'])
    untracked = subprocess.check_output(['git', '-C', str(qemu), 'ls-files', '--others', '--exclude-standard'])
    if untracked or (current and current != expected):
        raise RuntimeError('QEMU contains edits outside the reviewed recipe patches; preserve them in a separate checkout')
    if not current:
        for patch in patches:
            subprocess.run(['git', '-C', str(qemu), 'apply', str(ROOT / patch['file'])], check=True)
    actual = subprocess.check_output(['git', '-C', str(qemu), 'diff', '--binary', 'HEAD'])
    if actual != expected:
        raise RuntimeError('Patched source does not match the expected recipe patch set')
    return patches
