#!/usr/bin/env python3
"""Stage verified release assets and checksum exactly the files being uploaded."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

PLATFORMS = {'linux-x86_64': 'linux', 'windows-x86_64': 'windows',
             'darwin-x86_64': 'darwin', 'darwin-aarch64': 'darwin_aarch64'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--target', choices=PLATFORMS, required=True)
    parser.add_argument('--verification-report', type=Path)
    args = parser.parse_args()
    assets = [path for path in args.dist.glob(f'sdk-repo-{PLATFORMS[args.target]}-emulator-*.zip')
              if '-debug-' not in path.name and '-symbols-' not in path.name]
    if len(assets) != 1:
        raise SystemExit(f'Expected exactly one runtime SDK for {args.target}')
    sdk = assets[0]
    provenance = args.dist / f'provenance-{args.target}.json'
    manifest = args.dist / f'manifest-{args.target}.xml'
    verification = args.verification_report or args.dist / f'sdk-verification-{args.target}.json'
    required = [sdk, provenance, manifest, args.dist / 'SOURCE_OFFER.md', verification]
    if args.target == 'windows-x86_64':
        required += [args.dist / 'windows-dependencies.json', args.dist / 'NOTICE.MSVC-RUNTIME.txt']
    for path in required:
        if not path.is_file():
            raise SystemExit(f'Required release asset missing: {path}')
    report, origin = json.loads(verification.read_text()), json.loads(provenance.read_text())
    if (report.get('status') != 'passed' or report.get('target') != args.target
            or report.get('sha256') != digest(sdk) or report.get('size') != sdk.stat().st_size
            or report.get('recipe_commit') != origin.get('recipe_commit')
            or origin.get('upstream_tests') != 'passed'):
        raise SystemExit('SDK release requires a successful native verification of these exact bytes')
    with zipfile.ZipFile(sdk) as zipped:
        if (json.loads(zipped.read('emulator/hub-provenance.json')) != origin or
                zipped.read('emulator/hub-source-manifest.xml') != manifest.read_bytes()):
            raise SystemExit('Source metadata changed after verification of the SDK')
    optional = [args.dist / name for name in (
        f'elf-requirements-{args.target}.json', 'SHA256SUMS-source',
        'SHA256SUMS-windows-helpers', 'windows-helpers-source-map.json',
        'windows-helpers-source-notice.md')]
    optional += list(args.dist.glob('engine-corresponding-source.tar.gz*'))
    optional += list(args.dist.glob('windows-helpers-corresponding-source-*.tar.gz'))
    files = {path.name: path for path in [*required, *optional] if path.is_file()}
    for name in ('SHA256SUMS-source', 'SHA256SUMS-windows-helpers'):
        if name in files:
            for line in files[name].read_text().splitlines():
                expected, filename = line.split('  ', 1)
                if filename not in files or digest(files[filename]) != expected:
                    raise SystemExit(f'Incomplete or changed corresponding source asset: {filename}')
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit('Choose an empty release staging directory; existing artifacts are preserved')
    args.out.mkdir(parents=True, exist_ok=True)
    for name, path in sorted(files.items()):
        destination = args.out / name
        try:
            destination.hardlink_to(path.resolve())
        except OSError:
            shutil.copy2(path, destination)
    checksum = args.out / f'SHA256SUMS-{args.target}'
    checksum.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in sorted(args.out.iterdir())
                               if path.is_file() and path != checksum), encoding='utf-8', newline='\n')
    print(f'Staged {len(files)} verified release assets for {args.target}; build-only archives remain in {args.dist}')


if __name__ == '__main__':
    main()
