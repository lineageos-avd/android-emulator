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
    if untracked:
        raise RuntimeError('QEMU contains untracked files outside the recipe patches')
    missing = patches if not current else []
    if current and current != expected:
        # A recipe update may add a patch to a previously patched checkout.
        # Undo recognized patches only in a throwaway index; reject any
        # residual user edits before touching the actual working tree.
        with tempfile.TemporaryDirectory(prefix='hub-existing-patches-') as temporary:
            env = os.environ | {'GIT_INDEX_FILE': str(Path(temporary) / 'index')}
            subprocess.run(['git', '-C', str(qemu), 'read-tree', 'HEAD'], env=env, check=True)
            subprocess.run(['git', '-C', str(qemu), 'add', '-u'], env=env, check=True)
            applied = set()
            for patch in reversed(patches):
                command = ['git', '-C', str(qemu), 'apply', '--cached', '--reverse']
                check = subprocess.run([*command, '--check', str(ROOT / patch['file'])], env=env, capture_output=True)
                if check.returncode == 0:
                    subprocess.run([*command, str(ROOT / patch['file'])], env=env, check=True)
                    applied.add(patch['file'])
            residual = subprocess.check_output(['git', '-C', str(qemu), 'diff', '--cached', '--binary', 'HEAD'], env=env)
            if residual:
                raise RuntimeError('QEMU contains edits outside the reviewed recipe patches; preserve them in a separate checkout')
            missing = [patch for patch in patches if patch['file'] not in applied]
    if missing:
        subprocess.run(['git', '-C', str(qemu), 'apply', *[str(ROOT / patch['file']) for patch in missing]], check=True)
    actual = subprocess.check_output(['git', '-C', str(qemu), 'diff', '--binary', 'HEAD'])
    if actual != expected:
        raise RuntimeError('Patched source does not match the expected recipe patch set')
    return patches
