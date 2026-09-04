#!/usr/bin/env python3
"""Attach exact source/provenance to the upstream binary distribution."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile

from source_patches import describe_patches

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--build-number', required=True)
    parser.add_argument('--recipe-commit', required=True)
    parser.add_argument('--tests-skipped', action='store_true')
    args = parser.parse_args()
    dist = args.dist
    dist.mkdir(parents=True, exist_ok=True)
    provenance = json.loads((ROOT / 'upstream.json').read_text())
    provenance.update(target=args.target, build_number=args.build_number,
                      recipe_commit=args.recipe_commit, applied_patches=describe_patches(),
                      upstream_tests='skipped' if args.tests_skipped else 'passed',
                      hardware_smoke_test='not-recorded')
    (dist / f'provenance-{args.target}.json').write_text(json.dumps(provenance, indent=2) + '\n')
    shutil.copy2(args.source / 'resolved-manifest.xml', dist / f'manifest-{args.target}.xml')
    candidates = [p for p in dist.glob('sdk-repo-*-emulator-*.zip') if '-symbols-' not in p.name and '-debug-' not in p.name]
    if len(candidates) != 1:
        raise SystemExit(f'Expected one upstream engine distribution, found {candidates}')
    with zipfile.ZipFile(candidates[0], 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        names = archive.namelist()
        if any(stat.S_ISLNK(item.external_attr >> 16) for item in archive.infolist()):
            raise SystemExit('Distribution contains symlinks unsupported by Hub safe extraction')
        if not any('NOTICE' in name for name in names):
            raise SystemExit('Distribution has no upstream NOTICE; refusing publication')
        archive.write(dist / f'provenance-{args.target}.json', 'emulator/hub-provenance.json')
        archive.write(args.source / 'resolved-manifest.xml', 'emulator/hub-source-manifest.xml')
    shutil.copy2(ROOT / 'SOURCE_OFFER.md', dist)
    with (dist / f'SHA256SUMS-{args.target}').open('w') as output:
        for path in sorted(dist.iterdir()):
            if path.is_file() and not path.name.startswith('SHA256SUMS'):
                with path.open('rb') as stream:
                    output.write(f'{hashlib.file_digest(stream, "sha256").hexdigest()}  {path.name}\n')


if __name__ == '__main__':
    main()
