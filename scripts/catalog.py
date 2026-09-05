#!/usr/bin/env python3
"""Advertise only completed, tested SDK archives with corresponding source."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

PLATFORMS = {
    'linux-x86_64': ('linux', 'x86_64', 'linux'),
    'windows-x86_64': ('windows', 'x86_64', 'windows'),
    'darwin-x86_64': ('macos', 'x86_64', 'darwin'),
    'darwin-aarch64': ('macos', 'aarch64', 'darwin_aarch64'),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--require-all-targets', action='store_true',
                        help='Require the complete matrix for automatic tag releases')
    args = parser.parse_args()
    entries = []
    if not list(args.dist.glob('engine-corresponding-source.tar.gz*')):
        raise SystemExit('Corresponding source archive missing')
    for target, (host_os, host_arch, upstream_target) in PLATFORMS.items():
        provenance_path = args.dist / f'provenance-{target}.json'
        if not provenance_path.is_file():
            if args.require_all_targets:
                raise SystemExit(f'Missing provenance for {target}')
            continue
        provenance = json.loads(provenance_path.read_text())
        if provenance['upstream_tests'] != 'passed':
            raise SystemExit(f'Refusing catalog publication for untested {target}')
        assets = [path for path in args.dist.glob(f'sdk-repo-{upstream_target}-emulator-*.zip')
                  if '-symbols-' not in path.name and '-debug-' not in path.name]
        if len(assets) != 1:
            raise SystemExit(f'Missing/ambiguous distribution for {target}: {assets}')
        asset = assets[0]
        with zipfile.ZipFile(asset) as archive:
            properties = dict(line.split('=', 1) for line in
                              archive.read('emulator/source.properties').decode().splitlines()
                              if '=' in line)
            version = properties['Pkg.Revision'].strip()
            embedded = json.loads(archive.read('emulator/hub-provenance.json'))
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:[.\-][A-Za-z0-9.\-]+)?', version):
            raise SystemExit(f'Invalid numeric SDK version for {target}: {version}')
        if provenance.get('sdk_version', version) != version or embedded != provenance:
            raise SystemExit(f'SDK/provenance mismatch for {target}')
        with asset.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        entries.append({'host_os': host_os, 'host_arch': host_arch,
                        'version': version, 'url': f'https://github.com/lineageos-avd/android-emulator/releases/download/{args.tag}/{asset.name}',
                        'size': asset.stat().st_size, 'sha256': digest,
                        'executable': 'emulator/emulator' + ('.exe' if host_os == 'windows' else '')})
    if not entries:
        raise SystemExit('No completed engine targets to publish')
    (args.dist / 'catalog.json').write_text(json.dumps({'schema_version': 1, 'engines': entries}, indent=2) + '\n')


if __name__ == '__main__':
    main()
