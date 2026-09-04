#!/usr/bin/env python3
"""Export each source repository at its locked commit, with licenses intact.

Prebuilt toolchains are fetched by the manifest, not republished as source.
Archives split below GitHub's 2 GiB per-asset limit and include SHA256SUMS.
"""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--dist', type=Path, required=True)
    args = parser.parse_args()
    args.dist.mkdir(parents=True, exist_ok=True)
    manifest = args.source / 'resolved-manifest.xml'
    archive_path = args.dist / 'engine-corresponding-source.tar.gz'
    with tarfile.open(archive_path, 'w:gz', compresslevel=3) as archive:
        archive.add(manifest, arcname='resolved-manifest.xml')
        for path in ['default.xml', 'upstream.json', 'SOURCE_OFFER.md', 'LICENSE', 'scripts', 'nix', 'flake.nix', 'flake.lock']:
            archive.add(ROOT / path, arcname='hub-build/' + path)
        for project in ET.parse(manifest).getroot().findall('project'):
            path = project.attrib.get('path', project.attrib['name'])
            # This repository holds the source tarballs and downstream patches
            # corresponding to linked prebuilt libraries (Qt, FFmpeg, etc.).
            if path.startswith('prebuilts/') and path != 'prebuilts/android-emulator-build/archive':
                continue
            checkout = args.source / path
            process = subprocess.Popen(['git', '-C', str(checkout), 'archive', '--format=tar', '--prefix=' + path + '/', project.attrib['revision']], stdout=subprocess.PIPE)
            with tarfile.open(fileobj=process.stdout, mode='r|') as source:
                for member in source:
                    archive.addfile(member, source.extractfile(member) if member.isfile() else None)
            if process.wait():
                raise SystemExit(f'git archive failed for {path}')
    # Split only if necessary. Both compressed archives and split pieces preserve all source.
    limit = 1900 * 1024 * 1024
    artifacts = [archive_path]
    if archive_path.stat().st_size > limit:
        artifacts = []
        with archive_path.open('rb') as source:
            index = 0
            while True:
                chunk = source.read(16 * 1024 * 1024)
                if not chunk:
                    break
                part = args.dist / (archive_path.name + f'.part{index:03}')
                with part.open('wb') as dest:
                    length = 0
                    while chunk:
                        dest.write(chunk)
                        length += len(chunk)
                        if length >= limit:
                            break
                        chunk = source.read(min(16 * 1024 * 1024, limit - length))
                artifacts.append(part)
                index += 1
        archive_path.unlink()
    with (args.dist / 'SHA256SUMS-source').open('w') as checksums:
        for path in artifacts:
            with path.open('rb') as source:
                checksums.write(f'{hashlib.file_digest(source, "sha256").hexdigest()}  {path.name}\n')


if __name__ == '__main__':
    main()
