#!/usr/bin/env python3
"""Record symbol-version requirements of every shipped Linux ELF, without execution."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def greatest(values, prefix):
    matches = [value[len(prefix):] for value in values if value.startswith(prefix)]
    return max(matches, key=lambda value: tuple(map(int, value.split('.')))) if matches else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--readelf', default='readelf')
    args = parser.parse_args()
    files, versions = [], set()
    for path in sorted(args.sdk.rglob('*')):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
            stream.seek(0)
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        info = subprocess.check_output([args.readelf, '--version-info', '--wide', str(path)], text=True)
        # Definitions are provided by a file; only 'needs' constrain consumers.
        needs = info.split('Version needs section', 1)[-1] if 'Version needs section' in info else ''
        required = set(re.findall(r'Name:\s+(GLIBC_[0-9.]+|GLIBCXX_[0-9.]+|CXXABI_[0-9.]+)', needs))
        versions.update(required)
        dynamic = subprocess.check_output([args.readelf, '-d', '--wide', str(path)], text=True)
        files.append({'path': path.relative_to(args.sdk).as_posix(), 'sha256': digest,
                      'glibc': greatest(required, 'GLIBC_'), 'glibcxx': greatest(required, 'GLIBCXX_'),
                      'cxxabi': greatest(required, 'CXXABI_'),
                      'needed_libraries': re.findall(r'Shared library: \[([^]]+)\]', dynamic)})
    if not files:
        raise SystemExit('No ELF files found in SDK')
    report = {'schema_version': 1, 'target': 'linux-x86_64',
              'max_glibc': greatest(versions, 'GLIBC_'), 'max_glibcxx': greatest(versions, 'GLIBCXX_'),
              'max_cxxabi': greatest(versions, 'CXXABI_'), 'files': files,
              'scope': 'Version requirements of shipped ELF files, not the separate Hub application.',
              'limitation': 'Host libraries and graphics drivers may impose additional requirements; this is not an old-distribution runtime test.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['target', 'max_glibc', 'max_glibcxx', 'max_cxxabi']}))


if __name__ == '__main__':
    main()
