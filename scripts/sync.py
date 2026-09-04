#!/usr/bin/env python3
"""Sync immutable AOSP project commits using Google's own repo tool."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPO_VERSION = 'v2.58'
REPO_LAUNCHER = 'https://storage.googleapis.com/git-repo-downloads/repo'


def run(*command, **kwargs):
    subprocess.run([str(value) for value in command], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--revision', default='main', help='Recipe manifest commit/tag to synchronize')
    parser.add_argument('--manifest-url', default='https://github.com/lineageos-avd/android-emulator.git')
    args = parser.parse_args()
    source = args.source.resolve()
    source.mkdir(parents=True, exist_ok=True)
    # Prevent accidentally mixing this build with a user's existing Android tree.
    marker = source / '.emulator-hub-engine'
    if (source / '.repo').exists() and not marker.exists():
        raise SystemExit('Refusing unmanaged repo checkout: choose a new source directory')
    marker.write_text('lineageos-avd/android-emulator\n')
    tools = source / '.hub-tools'
    tools.mkdir(exist_ok=True)
    launcher = tools / 'repo'
    if not launcher.exists():
        urllib.request.urlretrieve(REPO_LAUNCHER, launcher)
    # The bootstrap loader verifies the explicitly selected, signed repo release.
    repo = [sys.executable, str(launcher)]
    env = os.environ.copy()
    env.setdefault('GIT_AUTHOR_NAME', 'Emulator Hub builder')
    env.setdefault('GIT_AUTHOR_EMAIL', 'build@users.noreply.github.com')
    env.setdefault('GIT_COMMITTER_NAME', env['GIT_AUTHOR_NAME'])
    env.setdefault('GIT_COMMITTER_EMAIL', env['GIT_AUTHOR_EMAIL'])
    run(*repo, 'init', '-u', args.manifest_url, '-b', args.revision,
        '--depth=1', '--repo-rev=' + REPO_VERSION, '--no-clone-bundle',
        '--platform=' + platform.system().lower(), cwd=source, env=env)
    run(*repo, 'sync', '-c', '--no-clone-bundle', '--no-tags', '--fail-fast',
        '-j', str(args.jobs), cwd=source, env=env)
    run(*repo, 'manifest', '-r', '-o', source / 'resolved-manifest.xml', cwd=source, env=env)
    lock = json.loads((ROOT / 'upstream.json').read_text())
    actual = subprocess.check_output(['git', '-C', str(source / 'external/qemu'), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != lock['qemu_revision']:
        raise SystemExit(f'QEMU revision mismatch: expected {lock["qemu_revision"]}, found {actual}')
    print(f'Synchronized verified QEMU {actual} in {source}')


if __name__ == '__main__':
    main()
