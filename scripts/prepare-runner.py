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
selected = None
for version in ['14.5', '15.1', '15.0']:
    candidates = [Path('/Library/Developer/CommandLineTools/SDKs') / f'MacOSX{version}.sdk']
    candidates += [path / f'Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX{version}.sdk' for path in Path('/Applications').glob('Xcode*.app')]
    selected = next((path.resolve() for path in candidates if path.is_dir()), None)
    if selected:
        break
if selected:
    xcode = next((path for path in selected.parents if path.suffix == '.app'), None)
    developer = xcode / 'Contents/Developer' if xcode else Path('/Library/Developer/CommandLineTools')
    # This script already rejects non-GitHub-hosted machines above.
    subprocess.run(['sudo', 'xcode-select', '--switch', str(developer)], check=True)
    active = developer.resolve()
    with open(os.environ['GITHUB_ENV'], 'a') as envfile:
        envfile.write(f'EMULATOR_MACOS_SDK={selected}\nDEVELOPER_DIR={developer}\n')
    print(f'Using compatible installed SDK: {selected}', flush=True)
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
