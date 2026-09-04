#!/usr/bin/env python3
"""Create the engine catalog only from a complete verified release artifact set."""
import argparse
import hashlib
import json
from pathlib import Path

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
    args = parser.parse_args()
    entries = []
    if not list(args.dist.glob('engine-corresponding-source.tar.gz*')):
        raise SystemExit('Corresponding source archive missing')
    for target, (host_os, host_arch, upstream_target) in PLATFORMS.items():
        provenance = json.loads((args.dist / f'provenance-{target}.json').read_text())
        if provenance['upstream_tests'] != 'passed':
            raise SystemExit(f'Refusing catalog publication for untested {target}')
        assets = list(args.dist.glob(f'sdk-repo-{upstream_target}-emulator-*.zip'))
        if len(assets) != 1:
            raise SystemExit(f'Missing/ambiguous distribution for {target}: {assets}')
        asset = assets[0]
        with asset.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        entries.append({'host_os': host_os, 'host_arch': host_arch,
                        'version': args.tag, 'url': f'https://github.com/lineageos-avd/android-emulator/releases/download/{args.tag}/{asset.name}',
                        'size': asset.stat().st_size, 'sha256': digest,
                        'executable': 'emulator/emulator' + ('.exe' if host_os == 'windows' else '')})
    (args.dist / 'catalog.json').write_text(json.dumps({'schema_version': 1, 'engines': entries}, indent=2) + '\n')


if __name__ == '__main__':
    main()
