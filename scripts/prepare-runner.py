#!/usr/bin/env python3
"""Reclaim bundled SDK space only on GitHub's disposable macOS runners."""
import os
from pathlib import Path
import platform
import shutil
import subprocess

if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
    raise SystemExit('This cleanup is restricted to disposable GitHub-hosted runners')
if platform.system() != 'Darwin':
    raise SystemExit('Only macOS runner preparation is supported')
subprocess.run(['df', '-h', '/'], check=True)
active = Path(subprocess.check_output(['xcode-select', '-p'], text=True).strip()).resolve()
for xcode in Path('/Applications').glob('Xcode*.app'):
    if xcode.resolve() not in active.parents:
        print(f'Removing unused preinstalled SDK: {xcode}', flush=True)
        subprocess.run(['sudo', 'rm', '-rf', str(xcode)], check=True)
# Emulator is compiled with the recorded upstream tools and Xcode. These optional
# image packages are unrelated to the engine build or its upstream unit tests.
for path in [Path('/Users/runner/Library/Android'), Path('/Applications/Android Studio.app'),
             Path('/usr/local/share/dotnet'), Path('/Users/runner/Library/Caches/Homebrew')]:
    if path.exists():
        print(f'Removing unused preinstalled SDK: {path}', flush=True)
        subprocess.run(['sudo', 'rm', '-rf', str(path)], check=True)
subprocess.run(['df', '-h', '/'], check=True)
print(f'Free bytes for source/build: {shutil.disk_usage("/").free}')
